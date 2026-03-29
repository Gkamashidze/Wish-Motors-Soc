import os
import io
import json
import logging
import requests
import re
from functools import wraps
from google import genai as google_genai
from google.genai import types as genai_types
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

FONT_BOLD = "/tmp/geo_bold.ttf"
FONT_REG  = "/tmp/geo_reg.ttf"

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

SYSTEM_PROMPT = """შენი როლი და კონტექსტი:
შენ ხარ "Wish Motors"-ის მთავარი მარკეტინგული სტრატეგი და კრეატიული დირექტორი. Wish Motors არის ავტონაწილების და სერვისის სპეციალიზებული ცენტრი ქალაქ ბათუმში (მისამართი: თევდორე მღვდლის #6), რომელიც მკაცრად ორიენტირებულია SsangYong-ის მოდელებზე (Rexton, Korando, Actyon, Tivoli, Turismo, Torres). მე ვარ ბიზნესის მფლობელი, მაღალი კლასის ავტო-ელექტრიკოსი და დიაგნოსტიკოსი.

ბიზნესის პრინციპები და დეტალები:
აპარატურა: ვმუშაობ პროფესიონალური აპარატურით — ვიყენებ მხოლოდ Autel-ის სკანერებს და ინსტრუმენტებს (Xhorse არ გამოიყენება!).
პროდუქცია: ვყიდით როგორც ორიგინალ (OEM), ასევე მაღალხარისხიან ალტერნატიულ ნაწილებს. მომხმარებელთან ვართ აბსოლუტურად გამჭვირვალეები.
ლოგისტიკა: გვაქვს უფასო მიტანა ბათუმში. 150 ლარზე ზევით ან 5 ნაწილის შეძენისას — უფასო გზავნა მთელ საქართველოში.
საკონტაქტო ინფო: ტელ: 555 966 428, WhatsApp: +995 555 966 428. FB ჯგუფი: https://shorturl.at/wxMWE

წესები პოსტის ტექსტისთვის:
- ყოველთვის დაურთე მიმზიდველი სათაური
- არ მომმართო ტექსტში პირადად და ამოიღე ზედმეტი სიტყვები (მაგ: არ გამოიყენო მომართვა "ექსპერტო")
- არასდროს მისცე მომხმარებელს რჩევა, რომ მიმართოს სხვა პროფესიონალს
- გამოიყენე შესაბამისი და ზომიერი რაოდენობის emoji
- არ გამოიყენო markdown ფორმატირება (*, **, #)
- არ გამოიყენო ჰეშთეგები

მნიშვნელოვანი სისტემური წესები:
ტექნიკური სიზუსტე: სითხეებზე, ნაწილებსა და მოვლაზე პოსტის წერისას, ინფორმაცია უნდა ეფუძნებოდეს მხოლოდ SsangYong/KGM-ის ოფიციალურ (OEM) რეკომენდაციებს. აუცილებლად ჩაშალე მონაცემები კონკრეტული მოდელებისა და ძრავების მიხედვით და მიუთითე ზუსტი დეტალები: ლიტრაჟი, სიბლანტე და დაშვება. მოერიდე ზოგად საუბარს."""

IMAGE_SYSTEM_PROMPT = """შენ უნდა შექმნა მაღალი ხარისხის 3D ანიმაციური პოსტერი (Pixar-ის/Disney-ს სტილში), რომელიც ზუსტად შეესაბამება მოცემული სარეკლამო პოსტის შინაარსს.

ვიზუალური წესები:
სტილი: 3D ანიმაცია, Expressive character design, Detailed textures.
ფერთა გამა: მუქი ლურჯი (Navy Blue) და ცისფერი (Cyan) — დომინანტი ფერები.
ლოკაცია: Wish Motors-ის სერვის ცენტრი ბათუმში. კედელზე ჩანდეს: "WISH MOTORS" და "ბათუმი, თევდორე მღვდლის #6".

პერსონაჟი: პროფესიონალი, სანდო, მეგობრული ხელოსანი. ეცვას Wish Motors-ის მუქ ლურჯ კომბინეზონი "WM" ლოგოთი. პოზა და ქმედება ასახავდეს პოსტის თემას.

SsangYong მოდელები: პოსტერზე გამოხატე კონკრეტული მოდელები თემის მიხედვით (Rexton, Torres, Korando, Tivoli, Turismo, Actyon).

თუ დიაგნოსტიკაა: ხელოსანს ხელში Autel სკანერი (ლოგო მკაფიოდ!), მიერთებული მანქანასთან. Xhorse — არასდროს!
თუ მოვლა/სითხეებია: OEM ნაწილები, ზეთის ბოთლები (5W-30, MB 229.51), ტექნიკური მონაცემები (6.0L, 8.5L).

ატმოსფერო: პროფესიონალური, ენერგიული, სუფთა. განათება თბილი, Pixar-სტილი."""

def ensure_fonts():
    if not os.path.exists(FONT_BOLD):
        try:
            r = requests.get("https://github.com/google/fonts/raw/main/ofl/notosansgeorgian/static/NotoSansGeorgian-Bold.ttf", timeout=15)
            r.raise_for_status()
            with open(FONT_BOLD, 'wb') as f: f.write(r.content)
        except Exception as e:
            logger.warning(f"Bold font download failed: {e}")
    if not os.path.exists(FONT_REG):
        try:
            r = requests.get("https://github.com/google/fonts/raw/main/ofl/notosansgeorgian/static/NotoSansGeorgian-Regular.ttf", timeout=15)
            r.raise_for_status()
            with open(FONT_REG, 'wb') as f: f.write(r.content)
        except Exception as e:
            logger.warning(f"Regular font download failed: {e}")

def owner_only(func):
    @wraps(func)
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
        user_prompt = """დაწერე Facebook პოსტი SsangYong-ის მანქანების მოვლის შესახებ.
თემა: სითხეები, ნაწილები ან ტექნიკური მოვლა — აირჩიე კონკრეტული და საინტერესო.
პოსტი: 150-200 სიტყვა. დაიცავი ყველა სისტემური წესი."""
    else:
        user_prompt = """დაწერე Facebook პოსტი SsangYong მანქანების ელექტრული სისტემებისა და დიაგნოსტიკის შესახებ.
თემა: ECU, ABS, სენსორები, ან სხვა ელ. სისტემა — აირჩიე კონკრეტული.
პოსტი: 150-200 სიტყვა. დაიცავი ყველა სისტემური წესი."""

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=user_prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT
        )
    )
    text = re.sub(r'\*+', '', response.text)
    text = re.sub(r'#+\s?', '', text)
    return text.strip()

IMAGE_SYSTEM_PROMPT = """შენ უნდა შექმნა მაღალი ხარისხის 3D ანიმაციური პოსტერი (Pixar-ის/Disney-ს სტილში), რომელიც ზუსტად შეესაბამება მოცემული სარეკლამო პოსტის შინაარსს.

ვიზუალური წესები:
სტილი: 3D ანიმაცია, Expressive character design, Detailed textures.
ფერთა გამა: მუქი ლურჯი (Navy Blue) და ცისფერი (Cyan) — დომინანტი ფერები.
ლოკაცია: Wish Motors-ის სერვის ცენტრი ბათუმში. კედელზე ჩანდეს: "WISH MOTORS" და "ბათუმი, თევდორე მღვდლის #6".

პერსონაჟი: პროფესიონალი, სანდო, მეგობრული ხელოსანი. ეცვას Wish Motors-ის მუქ ლურჯ კომბინეზონი "WM" ლოგოთი. პოზა და ქმედება ასახავდეს პოსტის თემას.

SsangYong მოდელები: პოსტერზე გამოხატე კონკრეტული მოდელები თემის მიხედვით (Rexton, Torres, Korando, Tivoli, Turismo, Actyon).

თუ დიაგნოსტიკაა: ხელოსანს ხელში Autel სკანერი (ლოგო მკაფიოდ!), მიერთებული მანქანასთან. Xhorse — არასდროს!
თუ მოვლა/სითხეებია: OEM ნაწილები, ზეთის ბოთლები (5W-30, MB 229.51), ტექნიკური მონაცემები (6.0L, 8.5L).

ატმოსფერო: პროფესიონალური, ენერგიული, სუფთა. განათება თბილი, Pixar-სტილი."""

def generate_ai_image(post_type, text):
    client = google_genai.Client(api_key=GEMINI_API_KEY)
    short = text[:400] if len(text) > 400 else text

    user_prompt = f"""შექმენი პოსტერი შემდეგი სარეკლამო პოსტის მიხედვით:

პოსტის ტიპი: {"მოვლა / ნაწილები / სითხეები" if post_type == "maintenance" else "ელექტრო დიაგნოსტიკა"}

პოსტის შინაარსი:
{short}

პოსტერი 1080x1080 პიქსელი, კვადრატული ფორმატი."""

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=user_prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=IMAGE_SYSTEM_PROMPT,
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
        gr = requests.post(
            f"https://graph.facebook.com/v21.0/{FB_GROUP_ID}/photos",
            files={'source': ('poster.png', io.BytesIO(image), 'image/png')},
            data={'caption': text, 'access_token': FB_PAGE_ACCESS_TOKEN}
        ).json()
        if 'error' in gr:
            logger.warning(f"ჯგუფში გაზიარება ვერ მოხერხდა: {gr['error']['message']}")

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
    await generate_and_send(context.application)

def main():
    ensure_fonts()
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
