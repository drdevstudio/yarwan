import asyncio
import nest_asyncio
import random
import string
import csv
import os
from aiohttp import web
from playwright.async_api import async_playwright
from pyvirtualdisplay import Display
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

nest_asyncio.apply()

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_TOKEN_HERE")
CSV_PATH = "accounts.csv"
CONCURRENCY_LIMIT = 3  # Number of simultaneous browsers

# --- GLOBAL STATE ---
total_created = 0
total_failed = 0
batch_count = 0
account_buffer = []
subscribed_users = set()  # Stores Telegram chat IDs
state_lock = asyncio.Lock()  # Ensures thread-safe counting

# --- GENERATOR FUNCTIONS ---
def generate_phone():
    """Generates a random 10-digit Indian phone number starting with 6, 7, 8, or 9"""
    return random.choice(['6', '7', '8', '9']) + "".join([str(random.randint(0, 9)) for _ in range(9)])

def generate_password():
    """Generates a random strong alphanumeric password (10-12 chars)"""
    length = random.randint(10, 12)
    pwd = [
        random.choice(string.ascii_lowercase),
        random.choice(string.ascii_uppercase),
        random.choice(string.digits)
    ]
    pwd += random.choices(string.ascii_letters + string.digits, k=length - 3)
    random.shuffle(pwd)
    return "".join(pwd)

def generate_device_id():
    """Generates a random 32-character hex string to spoof the deviceId"""
    return "".join(random.choices("0123456789abcdef", k=32))

# --- TELEGRAM BOT LOGIC ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command"""
    chat_id = update.effective_chat.id
    subscribed_users.add(chat_id)
    welcome_msg = (
        "🤖 *Welcome to the Account Generator Bot!*\n"
        "🔥 *Bot by Dr. Dev*\n\n"
        "I am running in the background, creating accounts at high speed.\n\n"
        "📌 *Commands:*\n"
        "`/count` - View real-time creation stats.\n"
        "`/get` - Fetch the latest accounts.csv file instantly.\n\n"
        "🔔 *Notifications:*\n"
        "You will automatically receive the CSV file here every time *100 accounts* are successfully created."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def get_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /get command"""
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, 'rb') as doc:
            await update.message.reply_document(document=doc, caption="📂 Here is your latest data.")
    else:
        await update.message.reply_text("⚠️ No accounts have been generated yet.")

async def count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /count command to show current stats"""
    msg = (
        "📊 *Current Status Report*\n\n"
        f"👷 *Active Workers:* {CONCURRENCY_LIMIT}\n"
        f"✅ *Total Created:* {total_created}\n"
        f"❌ *Total Failed:* {total_failed}\n"
        f"📦 *Progress to next batch:* {total_created % 100}/100\n\n"
        f"🔥 *Bot by Dr. Dev*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def broadcast_batch(bot_app: Application):
    """Sends the 100-account milestone message to all users"""
    global batch_count
    msg = (
        f"🎉 *100-Account Batch Completed!*\n\n"
        f"✅ Total Created So Far: {total_created}\n"
        f"❌ Total Failed So Far: {total_failed}\n\n"
        f"🔥 *Bot by Dr. Dev*"
    )
    for chat_id in list(subscribed_users):
        try:
            await bot_app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            if os.path.exists(CSV_PATH):
                with open(CSV_PATH, 'rb') as doc:
                    await bot_app.bot.send_document(chat_id=chat_id, document=doc)
        except Exception as e:
            print(f"Failed to send to Telegram: {e}")

async def save_to_csv():
    """Saves buffer to CSV immediately"""
    global account_buffer
    if not account_buffer: return
    with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(account_buffer)
    account_buffer.clear()

# --- PLAYWRIGHT WORKER ---
async def create_account_worker(worker_id, browser, bot_app):
    global total_created, total_failed, account_buffer, batch_count

    await asyncio.sleep(worker_id * 2.0) # Stagger start times to avoid Cloudflare blocks

    while True:
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        phone = generate_phone()
        password = generate_password()
        fake_device_id = generate_device_id()
        captured_payload = None
        payload_captured_event = asyncio.Event()

        # Inject fake device ID
        await page.add_init_script(f"window.localStorage.setItem('arvId', '{fake_device_id}');")

        async def handle_request(route):
            nonlocal captured_payload
            request = route.request
            # Block heavy resources, allow stylesheets for layout clicks
            if request.resource_type in ["image", "media", "font"]:
                await route.abort()
                return
            
            if "api/webapi/Register" in request.url and "RegisterState" not in request.url:
                captured_payload = request.post_data
                payload_captured_event.set()
                
            await route.continue_()

        await page.route("**/*", handle_request)

        success = False
        try:
            await page.goto("https://bdgwinkk.com/#/register?invitationCode=2875715337609", timeout=20000)
            await page.wait_for_selector('input[placeholder="Please enter the phone number"]', timeout=10000)

            await page.fill('input[placeholder="Please enter the phone number"]', phone)
            await page.fill('input[placeholder="Set password"]', password)
            await page.fill('input[placeholder="Confirm password"]', password)
            
            await page.evaluate("document.querySelector('.van-checkbox__icon').click()")
            await page.click('button:has-text("Register")', force=True)

            try:
                await asyncio.wait_for(payload_captured_event.wait(), timeout=5.0)
                if captured_payload:
                    success = True
            except asyncio.TimeoutError:
                pass
        except Exception:
            pass
        finally:
            await context.close()

        # Safely update global counts and trigger Telegram bot
        async with state_lock:
            if success:
                total_created += 1
                account_buffer.append([phone, password, captured_payload])
                print(f"[Worker-{worker_id} ✅] Phone: {phone} | Total OK: {total_created}")
                
                # Save to CSV IMMEDIATELY on every success
                await save_to_csv()

                # Trigger Telegram Broadcast every 100 accounts
                current_batch = total_created // 100
                if current_batch > batch_count and total_created % 100 == 0:
                    batch_count = current_batch
                    await broadcast_batch(bot_app)
            else:
                total_failed += 1
                print(f"[Worker-{worker_id} ❌] Failed | Fails: {total_failed}")

        await asyncio.sleep(1.0)

# --- DUMMY WEB SERVER FOR RENDER ---
async def web_handler(request):
    return web.Response(text="Bot by Dr. Dev is successfully running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- MAIN EXECUTION ---
async def main():
    # Setup CSV
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(["Phone", "Password", "Payload"])

    print("🚀 Starting Web Server...")
    await start_web_server()

    print("🤖 Starting Telegram Bot...")
    tg_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start_cmd))
    tg_app.add_handler(CommandHandler("get", get_cmd))
    tg_app.add_handler(CommandHandler("count", count_cmd)) # New count command
    
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()

    print(f"🔥 Starting Playwright with {CONCURRENCY_LIMIT} workers...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=['--no-sandbox', '--disable-setuid-sandbox'])
        tasks = [asyncio.create_task(create_account_worker(i + 1, browser, tg_app)) for i in range(CONCURRENCY_LIMIT)]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Stopped.")
