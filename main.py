import os
import io
import json
import logging
import requests
from google import genai as google_genai
from google.genai import types as genai_types
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import re

FONT_BOLD = "/tmp/geo_bold.ttf"
FONT_REG  = "/tmp/geo_reg.ttf"

def ensure_fonts():
    if not os.path.exists(FONT_BOLD):
        try:
            r = requests.get("https://github.com/google/fonts/raw/main/ofl/notosansgeorgian/static/NotoSansGeorgian-Bold.ttf", timeout=15)
            with open(FONT_BOLD, 'wb') as f: f.write(r.content)
        except Exception as e:
            logger.warning(f"Bold font download failed: {e}")
    if not os.path.exists(FONT_REG):
        try:
            r = requests.get("https://github.com/google/fonts/raw/main/ofl/notosansgeorgian/static/NotoSansGeorgian-Regular.ttf", timeout=15)
            with open(FONT_REG, 'wb') as f: f.write(r.content)
        except Exception as e:
            logger.warning(f"Regular font download failed: {e}")

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

GEMINI_API_KEY       = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID     = os.environ["TELEGRAM_CHAT_ID"]
FB_PAGE_ACCESS_TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
FB_PAGE_ID           = os.environ["FB_PAGE_ID"]
FB_GROUP_ID          = os.environ.get("FB_GROUP_ID", "")
ALLOWED_USER_ID      = int(os.environ["TELEGRAM_CHAT_ID"])

NAVY  = (27,  45,  91)
CYAN  = (41, 171, 226)
WHITE = (255, 255, 255)
STATE_FILE = "state.json"

def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ALLOWED_USER_ID:
            await update.message.reply_text("⛔ წვდომა აკრძალულია")
            return
        return await func(update, context)
    return wrapper

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
    ensure_fonts()
    preferred = FONT_BOLD if bold else FONT_REG
    fallbacks = [
        preferred,
        "/usr/share/fonts/truetype/noto/NotoSansGeorgian-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansGeorgian-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in fallbacks:
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
    client = google_genai.Client(api_key=GEMINI_API_KEY)
    if post_type == "maintenance":
        prompt = """დაწერე საინტერესო Facebook პოსტი ქართულ ენაზე SsangYong-ის მანქანების მოვლის შესახებ.
პოსტი უნდა:
- შეიცავდეს 150-200 სიტყვა
- მოიცავდეს პრაქტიკულ რჩევებს SsangYong-ის (Musso, Rexton, Tivoli, Korando) მოვლასთან
- ახსენოს Wish Motors - ორიგინალი და შემცვლელი ნაწილების მიმწოდებელი
- დასრულდეს Call-to-Action-ით
- შეიცავდეს 3-4 emoji
- იყოს მეგობრული და პროფესიონალური
- არ შეიცავდეს ჰეშთეგებს
- არ გამოიყენო markdown ფორმატირება, არავითარი *, **, # სიმბოლო"""
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
- არ შეიცავდეს ჰეშთეგებს
- არ გამოიყენო markdown ფორმატირება, არავითარი *, **, # სიმბოლო"""
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    text = re.sub(r'\*+', '', response.text)
    text = re.sub(r'#+\s?', '', text)
    return text.strip()

def generate_ai_image(post_type, text):
    client = google_genai.Client(api_key=GEMINI_API_KEY)
    short = text[:300] if len(text) > 300 else text
    if post_type == "maintenance":
        prompt = f"""Create a professional square 1080x1080 advertisement poster in Pixar/Disney 3D animation style.
Scene: Bright modern automotive service center, clean white and blue interior.
Main character: Friendly 3D cartoon mechanic in navy blue SsangYong uniform, smiling.
Background: Two SsangYong SUVs (Rexton and Korando), oil bottles, spare parts on shelves.
Text overlay at top of image - orange bordered info boxes with this content:
"Wish Motors - SsangYong სპეციალიზებული ცენტრი"
"{short[:150]}"
Colors: Navy blue #1B2D5B and cyan #29ABE2 accents. Bright, colorful, high quality 3D render.
No dark overlays. Professional commercial advertisement look."""
    else:
        prompt = f"""Create a professional square 1080x1080 advertisement poster in Pixar/Disney 3D animation style.
Scene: Bright modern automotive diagnostics center with glowing equipment.
Main character: Friendly 3D cartoon mechanic in navy blue uniform holding diagnostic tablet with glowing screen.
Background: SsangYong SUV connected to diagnostic computer, ECU circuit visualization, electric blue glow.
Text overlay at top of image - orange bordered info boxes with this content:
"Wish Motors - SsangYong ელ. დიაგნოსტიკა"
"{short[:150]}"
Colors: Navy blue #1B2D5B and cyan #29ABE2 with electric glow effects. Bright, colorful, high quality 3D render.
No dark overlays. Professional commercial advertisement look."""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_modalities=['image']
            )
        )
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                return part.inline_data.data
        return None
    except Exception as e:
        logger.warning(f"AI სურათი ვერ შეიქმნა: {e}")
        return None
        
def create_poster(post_type, text, ai_image_bytes=None):
    W, H = 1080, 1080
    if ai_image_bytes:
        try:
            img = Image.open(io.BytesIO(ai_image_bytes)).resize((W, H)).convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        except Exception:
            pass
    # Fallback
    img = Image.new('RGB', (W, H), NAVY)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 10], fill=CYAN)
    draw.rectangle([0, H-10, W, H], fill=CYAN)
    f = load_font(60, bold=True)
    draw.text((40, 40), "WISH MOTORS", font=f, fill=WHITE)
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
        f"https://graph.facebook.com/v21.0/{FB_PAGE_ID}/photos",
        files={'source': ('poster.png', io.BytesIO(image), 'image/png')},
        data={'caption': text, 'access_token': FB_PAGE_ACCESS_TOKEN}
    ).json()
    if 'error' in r:
        raise Exception(r['error']['message'])
    if FB_GROUP_ID:
        requests.post(
            f"https://graph.facebook.com/v21.0/{FB_GROUP_ID}/photos",
            files={'source': ('poster.png', io.BytesIO(image), 'image/png')},
            data={'caption': text, 'access_token': FB_PAGE_ACCESS_TOKEN}
        )

async def generate_and_send(app):
    global pending
    post_type = get_post_type()
    try:
        await app.bot.send_message(TELEGRAM_CHAT_ID, "🔄 პოსტს ვქმნი, მოიცა...")
        text     = generate_text(post_type)
        ai_image = generate_ai_image(post_type, text)
        image    = create_poster(post_type, text, ai_image)
        pending  = {'type': post_type, 'text': text, 'image': image}
        await send_for_approval(app, post_type, text, image)
    except Exception as e:
        logger.error(e)
        await app.bot.send_message(TELEGRAM_CHAT_ID, f"❌ შეცდომა: {e}")

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
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

@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Wish Motors Bot გამართულია!\n\n"
        "📅 პოსტი ავტომატურად გაიგზავნება ორშაბათს და ხუთშაბათს 10:00-ზე.\n"
        "⚡ ახლა სატესტოდ: /generate"
    )

@owner_only
async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CallbackQueryHandler(on_callback))

    scheduler = AsyncIOScheduler(timezone="Asia/Tbilisi")
    scheduler.add_job(generate_and_send, 'cron',
                      day_of_week='mon,thu', hour=10, minute=0, args=[app])
    scheduler.start()

    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
