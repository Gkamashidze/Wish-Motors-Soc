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

MASTER_PROMPT = """You are the fully automated Chief Marketing Strategist and Creative Director for "Wish Motors", a specialized auto parts and service center in Batumi, Georgia (Address: 6 Tevdore Mgvdli Str.). 
The business exclusively services and sells parts for SsangYong/KGM models (Rexton, Korando, Actyon, Tivoli, Turismo, Torres). 
The owner is a high-level automotive electrician and diagnostic specialist.

CRITICAL BUSINESS RULES:
1. Equipment: Only "Autel" diagnostic scanners and tools are used. NEVER mention or generate "Xhorse" equipment.
2. Parts: Selling OEM and high-quality aftermarket parts with absolute transparency.
3. Logistics: Free delivery within Batumi. Free nationwide shipping (Georgia) for orders over 150 GEL or 5+ items.
4. Contact Info (MUST be in every ad): Tel: 555 966 428 | WhatsApp: +995 555 966 428 | FB Group: https://shorturl.at/wxMWE

YOUR TASK:
I will provide you with a [TARGET_CATEGORY]. 
Step 1: Autonomously select a highly specific, useful topic within that category tailored to SsangYong vehicles.
Step 2: Generate exactly two output blocks without ANY conversational filler, greetings, or explanations. Just the blocks.

[TARGET_CATEGORY] = {current_category}

--- CATEGORY LOGIC FOR TOPIC SELECTION ---
If TARGET_CATEGORY is "AUTO-ELECTRICAL/DIAGNOSTICS":
Select a topic like DPF forced regeneration via scanner, sensor diagnostics, ECU programming, ABS/ESP troubleshooting, or resolving Check Engine issues. Focus on the precision of the "Autel" scanner and the owner's expert skills.

If TARGET_CATEGORY is "MAINTENANCE/PARTS/FLUIDS":
Select a topic like Automatic Transmission Fluid (ATF), Antifreeze/Coolant, Brake Pads, or Filters. 
CRITICAL RULE: You MUST provide exact technical specifications (OEM recommendations) broken down by SsangYong models (e.g., Korando Sports 2.0/2.2, Rexton G4, Tivoli, Torres). Include capacities (Liters), exact fluid specs (e.g., DOT4, ATF 3292/DSIH 6P805, etc.), and maintenance intervals. Do not give generic advice.

--- OUTPUT FORMAT ---

[IMAGE_PROMPT]
Write a highly detailed prompt for a Text-to-Image AI in English based on the specific topic you chose.
- Style: High-quality 3D animation (Pixar/Disney style), cinematic lighting.
- Colors: Brand colors must dominate (Navy Blue and Cyan).
- Scene: Inside the modern Wish Motors service center in Batumi. Wall text must say "WISH MOTORS" and "ბათუმი, თევდორე მღვდლის #6".
- Character: Include a friendly, expert mechanic wearing a Navy Blue uniform with the "WISH MOTORS" logo.
- Details: Include relevant SsangYong models. Display relevant holographic tech data floating in the air based on the topic.
[/IMAGE_PROMPT]

[ADCOPY]
Write the social media post based on the topic you chose.
- Language: Georgian ONLY.
- Tone: Professional, highly informative, trustworthy. Do NOT use overly familiar greetings. Go straight to the point.
- Structure: Catchy title with emojis -> Brief explanation -> Detailed SsangYong specific data -> Wish Motors business rules -> Contact Info.
- Format strictly with bullet points and appropriate emojis.
[/ADCOPY]"""

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

def generate_content(post_type):
    client = google_genai.Client(api_key=GEMINI_API_KEY)
    category = "AUTO-ELECTRICAL/DIAGNOSTICS" if post_type == "electrical" else "MAINTENANCE/PARTS/FLUIDS"
    prompt = MASTER_PROMPT.replace("{current_category}", category)

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    raw = response.text

    image_prompt = ""
    adcopy = ""
    if "[IMAGE_PROMPT]" in raw and "[/IMAGE_PROMPT]" in raw:
        image_prompt = raw.split("[IMAGE_PROMPT]")[1].split("[/IMAGE_PROMPT]")[0].strip()
    if "[ADCOPY]" in raw and "[/ADCOPY]" in raw:
        adcopy = raw.split("[ADCOPY]")[1].split("[/ADCOPY]")[0].strip()

    adcopy = re.sub(r'\*+', '', adcopy)
    adcopy = re.sub(r'#+\s?', '', adcopy)
    return image_prompt, adcopy.strip()

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

def generate_ai_image(image_prompt):
    if not image_prompt:
        return None
    client = google_genai.Client(api_key=GEMINI_API_KEY)
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=image_prompt,
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
        image_prompt, text = generate_content(post_type)
        ai_image = generate_ai_image(image_prompt)
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
