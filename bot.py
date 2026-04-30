import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

from aiohttp import web
from dotenv import load_dotenv
from pyrogram import Client, idle
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import init_db, get_subscribers
from utils import get_new_releases, format_item_message
from config import UPDATE_INTERVAL_HOURS, CHAT_ID

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────
API_ID    = os.getenv("API_ID")
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT      = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN or not API_ID or not API_HASH:
    print("ERROR: BOT_TOKEN, API_ID and API_HASH are all required in .env")
    sys.exit(1)

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("OTTBot")

# ─── Initialize DB ────────────────────────────────────────────────────────────
init_db()

# ─── Pyrogram Client ──────────────────────────────────────────────────────────
bot = Client(
    "ott_bot",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins"),
)

# ─── Scheduler ────────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler(timezone="UTC")


async def send_updates():
    """Fetch new OTT releases and push them to all subscribers / channels."""
    logger.info("⏰ Scheduled job: checking for new releases …")
    items = await get_new_releases(days_back=7)
    if not items:
        logger.info("No new releases found this cycle.")
        return

    # Determine target chat IDs
    chat_ids: set[int] = set()
    if CHAT_ID:
        for cid in str(CHAT_ID).split(","):
            cid = cid.strip()
            if cid:
                chat_ids.add(int(cid))
    else:
        chat_ids.update(get_subscribers())

    if not chat_ids:
        logger.info("No subscribers or CHAT_ID set — skipping send.")
        return

    sent = 0
    for cid in chat_ids:
        for item in items:
            try:
                await bot.send_message(cid, format_item_message(item), disable_web_page_preview=False)
                sent += 1
                await asyncio.sleep(0.5)          # Respect Telegram rate-limits
            except Exception as exc:
                logger.warning(f"Failed to send to {cid}: {exc}")

    logger.info(f"✅ Sent {sent} message(s) across {len(chat_ids)} chat(s).")


# ─── Health-check HTTP server ─────────────────────────────────────────────────
async def _health(request):
    return web.Response(text="OK")


async def start_health_server():
    app_web = web.Application()
    app_web.router.add_get("/", _health)
    app_web.router.add_get("/health", _health)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health-check server listening on :{PORT}")


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    # Fire one job shortly after start, then repeat on interval
    first_run = datetime.now() + timedelta(seconds=15)
    scheduler.add_job(
        send_updates,
        "interval",
        hours=UPDATE_INTERVAL_HOURS,
        next_run_time=first_run,
        id="send_updates",
    )
    scheduler.start()
    logger.info(f"Scheduler started — updates every {UPDATE_INTERVAL_HOURS}h (first run in ~15s)")

    asyncio.create_task(start_health_server())

    await bot.start()
    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username} ({me.id})")

    await idle()          # Block until SIGINT/SIGTERM

    scheduler.shutdown(wait=False)
    await bot.stop()
    logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
