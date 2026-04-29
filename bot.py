import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from aiohttp import web
from dotenv import load_dotenv
from pyrogram import Client
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import init_db, get_subscribers
from utils import get_new_releases, format_item_message
from config import UPDATE_INTERVAL_HOURS, CHAT_ID

load_dotenv()

# ---------- Configuration ----------
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN or not API_ID or not API_HASH:
    logging.error("Missing API_ID, API_HASH or BOT_TOKEN")
    sys.exit(1)

PORT = int(os.getenv("PORT", "8080"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ---------- Initialize DB ----------
init_db()

# ---------- Pyrogram Client ----------
app = Client(
    "ott_bot",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")
)

# ---------- Scheduler for periodic updates ----------
scheduler = AsyncIOScheduler()

async def send_updates():
    """Send new releases to all subscribers or fixed chat."""
    logger.info("Checking for new releases...")
    items = await get_new_releases(days_back=7)
    if not items:
        logger.info("No new releases.")
        return
    chat_ids = set()
    if CHAT_ID:
        for cid in str(CHAT_ID).split(","):
            chat_ids.add(int(cid.strip()))
    else:
        chat_ids.update(get_subscribers())
    for cid in chat_ids:
        for item in items:
            try:
                await app.send_message(cid, format_item_message(item), parse_mode="Markdown")
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Failed to send to {cid}: {e}")
    logger.info(f"Sent {len(items)} releases to {len(chat_ids)} chats.")

# ---------- Health Check Server ----------
async def health_check(request):
    return web.Response(text="OK")

async def run_health_server():
    app_web = web.Application()
    app_web.router.add_get("/health", health_check)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health check server running on port {PORT}")
    await asyncio.Event().wait()

# ---------- Main ----------
async def main():
    # Schedule periodic updates – use datetime for next_run_time
    now = datetime.now()
    next_run = now + timedelta(seconds=10)
    scheduler.add_job(send_updates, 'interval', hours=UPDATE_INTERVAL_HOURS, next_run_time=next_run)
    scheduler.start()
    logger.info(f"Scheduled updates every {UPDATE_INTERVAL_HOURS} hours")
    
    # Start health server (non-blocking)
    asyncio.create_task(run_health_server())
    
    # Start bot (this blocks)
    await app.start()
    logger.info("Bot started")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
