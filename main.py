import os
import io
import json
import logging
import requests
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

GEMINI_API_KEY      = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID    = os.environ["TELEGRAM_CHAT_ID"]
FB_PAGE_ACCESS_TOKEN= os.environ["FB_PAGE_ACCESS_TOKEN"]
FB_PAGE_ID          = os.environ["FB_PAGE_ID"]
FB_GROUP_ID         = os.environ.get("FB_GROUP_ID", "")

NAVY  = (27,  45,  91)
CYAN  = (41, 171, 226)
WHITE = (255, 255, 255)

STATE_FILE = "state.json"

def get_post_type():
    try:
        with open(STATE_FILE) as f:
            last = json.load(f).get("last_type", "electrical")
    except Exception:
        last = "electrical"
    return "maintenance" if last == "electrical" else "electrical"

def save_post_type(t):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_type": t}, f)

def load_font(size, bold=False):
    paths = [
        f"/usr/share/fonts/truetype/noto/NotoSansGeorgian-{'Bold' if bold else 'Regular'}.ttf",
        f"/usr/share/fonts/noto/NotoSansGeorgian-{'Bold' if bold else 'Regular'}.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()

def wrap_text(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], []
    for word in words:
        cur.append(word)
        if draw.textbbox((0,0), ' '.join(cur), font=font)[2] > max_w and len(cur) > 1:
            cur.pop()
            lines.append(' '.join(cur))
            cur = [word]
    if cur:
        lines.append(' '.join(cur))
    return lines

def generate_text(post_type):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    if post_type == "maintenance":
        prompt = """დაწერე საინტერესო Facebook პოსტი ქართულ ენაზე SsangYong-ის მანქანების მოვლის შესახებ.
პოსტი უნდა:
- შეიცავდეს 150-200 სიტყვა
- მოიცავდეს პრაქტიკულ რჩევებს SsangYong-ის (Musso, Rexton, Tivoli, Korando) მოვლასთან
- ახსენოს Wish Motors - ორიგინალი და შემცვლელი ნაწილების მიმწოდებელი
- დასრულდეს Call-to-Action-ით
- შეიცავდეს 3-4 emoji
- იყოს მეგობრული და პროფესიონალური
- არ შეიცავდეს ჰეშთეგებს"""
    else:
        prompt = """დაწერე საინტერესო Facebook პოსტი ქართულ ენაზე SsangYong მანქანების ელექტრული სისტემებისა და დიაგნოსტიკის შესახებ.
პოსტი უნდა:
- შეიცავდეს 150-200 სიტყვა
- განიხილოს ელ. დიაგნოსტიკის მნიშვნელობა ან კონკრეტული სისტემა (ABS, ECU, სენსორები)
- ახსენოს Wish Motors - SsangYong-ის ელ. კომპონენტების მომწოდებელი
- ახსენოს პროფესიონალური ელ. დიაგნოსტიკის მომსახურება
- დასრულდეს Call-to-Action-ით
- შეიცავდეს 3-4 emoji
- იყოს მეგობრული და პროფესიონალური
- არ შეიცავდეს ჰეშთეგებს"""
    return model.generate_content(prompt).text.strip()

def create_poster(post_type, text):
    W, H = 1080, 1080
    img = Image.new('RGB', (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, W, 130], fill=NAVY)
    draw.rectangle([0, 130, W, 148], fill=CYAN)
    draw.rectangle([0, H-110, W, H], fill=NAVY)
    draw.rectangle([0, H-126, W, H-110], fill=CYAN)

    f_title  = load_font(54, bold=True)
    f_badge  = load_font(28, bold=True)
    f_sub    = load_font(24)
    f_body   = load_font(30)
    f_footer = load_font(25)

    draw.text((40, 30), "WISH MOTORS", font=f_title, fill=WHITE)

    badge = "🔧 SsangYong-ის მოვლა" if post_type == "maintenance" else "⚡ ელექტრო დიაგნოსტიკა"
    bx, by = 40, 168
    bb = draw.textbbox((bx, by), badge, font=f_badge)
    draw.rectangle([bx-10, by-8, bb[2]+10, bb[3]+8], fill=CYAN)
    draw.text((bx, by), badge, font=f_badge, fill=WHITE)

    short = text[:400] + "..." if len(text) > 400 else text
    lines = wrap_text(draw, short, f_body, W - 80)
    y = 250
    for line in lines[:14]:
        draw.text((40, y), line, font=f_body, fill=NAVY)
        y += 44

    draw.text((40, H-95),  "📞 Wish Motors | SsangYong Parts", font=f_footer, fill=WHITE)
    draw.text((40, H-60), "ორიგინალი და შემცვლელი ნაწილები",  font=f_footer, fill=CYAN)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()

pending = {}

async def send_for_approval(app, post_type, text, image):
    keyboard = [[
        InlineKeyboardButton("✅ დამტკიცება", callback_data="approve"),
        InlineKeyboardButton("❌ ხელახლა",    callback_data="reject")
    ]]
    label = "🔧 მოვლა" if post_type == "maintenance" else "⚡ ელ. დიაგნოსტიკა"
    caption = f"📋 ახალი პოსტი მზადაა\nტიპი: {label}\n\n{text[:900]}"
    await app.bot.send_photo(
        chat_id=TELEGRAM_CHAT_ID,
        photo=io.BytesIO(image),
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    if len(text) > 900:
        await app.bot.send_message(TELEGRAM_CHAT_ID, f"📝 სრული ტექსტი:\n\n{text}")

def post_to_facebook(text, image):
    r = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
        files={'source': ('poster.png', io.BytesIO(image), 'image/png')},
        data={'caption': text, 'access_token': FB_PAGE_ACCESS_TOKEN}
    ).json()
    if 'error' in r:
        raise Exception(r['error']['message'])
    if FB_GROUP_ID:
        requests.post(
            f"https://graph.facebook.com/v19.0/{FB_GROUP_ID}/photos",
            files={'source': ('poster.png', io.BytesIO(image), 'image/png')},
            data={'caption': text, 'access_token': FB_PAGE_ACCESS_TOKEN}
        )

async def generate_and_send(app):
    global pending
    post_type = get_post_type()
    try:
        await app.bot.send_message(TELEGRAM_CHAT_ID, "🔄 პოსტს ვქმნი, მოიცა...")
        text  = generate_text(post_type)
        image = create_poster(post_type, text)
        pending = {'type': post_type, 'text': text, 'image': image}
        await send_for_approval(app, post_type, text, image)
    except Exception as e:
        logger.error(e)
        await app.bot.send_message(TELEGRAM_CHAT_ID, f"❌ შეცდომა: {e}")

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending
    q = update.callback_query
    await q.answer()
    if q.data == "approve":
        if not pending:
            await q.edit_message_caption("❌ პოსტი ვეღარ მოიძებნა")
            return
        try:
            post_to_facebook(pending['text'], pending['image'])
            save_post_type(pending['type'])
            pending = {}
            await q.edit_message_caption("✅ პოსტი გაიზიარა Facebook-ზე!")
        except Exception as e:
            await q.edit_message_caption(f"❌ Facebook-ზე ვერ გაიზიარა: {e}")
    elif q.data == "reject":
        await q.edit_message_caption("🔄 ახლიდან ვქმნი...")
        await generate_and_send(context.application)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Wish Motors Bot გამართულია!\n\n"
        "📅 პოსტი ავტომატურად გაიგზავნება სამშაბათს და პარასკევს 10:00-ზე.\n"
        "⚡ ახლა სატესტოდ: /generate"
    )

async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await generate_and_send(context.application)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CallbackQueryHandler(on_callback))

    scheduler = AsyncIOScheduler(timezone="Asia/Tbilisi")
    scheduler.add_job(generate_and_send, 'cron',
                      day_of_week='tue,fri', hour=10, minute=0, args=[app])
    scheduler.start()

    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
