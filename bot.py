import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

from aiohttp import web
from dotenv import load_dotenv
from pyrogram import Client, idle, enums
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import init_db, close_db, get_subscribers
from utils import get_new_releases, format_item_message
from config import UPDATE_INTERVAL_HOURS, CHAT_ID, MONGO_URI

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────
API_ID    = os.getenv("API_ID")
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT      = int(os.getenv("PORT", "8080"))

missing = [k for k, v in {"BOT_TOKEN": BOT_TOKEN, "API_ID": API_ID,
                           "API_HASH": API_HASH, "MONGO_URI": MONGO_URI}.items() if not v]
if missing:
    print(f"ERROR: Missing required env vars: {', '.join(missing)}")
    sys.exit(1)

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("OTTBot")

# ─── Pyrogram Client ──────────────────────────────────────────────────────────
# parse_mode=HTML so plugins can use <b>, <i>, <code> without escaping issues
bot = Client(
    "ott_bot",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins"),
    parse_mode=enums.ParseMode.HTML,
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

    chat_ids: set[int] = set()
    if CHAT_ID:
        for cid in str(CHAT_ID).split(","):
            cid = cid.strip()
            if cid:
                chat_ids.add(int(cid))
    else:
        chat_ids.update(await get_subscribers())

    if not chat_ids:
        logger.info("No subscribers or CHAT_ID configured — skipping send.")
        return

    sent = 0
    for cid in chat_ids:
        for item in items:
            try:
                poster = item.get("poster", "")
                text   = format_item_message(item)
                if poster:
                    await bot.send_photo(cid, poster, caption=text,
                                         parse_mode=enums.ParseMode.HTML)
                else:
                    await bot.send_message(cid, text,
                                           parse_mode=enums.ParseMode.HTML,
                                           disable_web_page_preview=False)
                sent += 1
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.warning(f"Failed to send to {cid}: {exc}")

    logger.info(f"✅ Sent {sent} message(s) to {len(chat_ids)} chat(s).")


# ─── Health-check HTTP server ─────────────────────────────────────────────────
async def _health(request):
    return web.Response(text="OK")


async def start_health_server():
    app_web = web.Application()
    app_web.router.add_get("/",       _health)
    app_web.router.add_get("/health", _health)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health-check server listening on :{PORT}")


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    # 1. Connect MongoDB first (plugins import database at load time)
    await init_db()

    # 2. Schedule periodic updates
    first_run = datetime.utcnow() + timedelta(seconds=20)
    scheduler.add_job(
        send_updates,
        "interval",
        hours=UPDATE_INTERVAL_HOURS,
        next_run_time=first_run,
        id="send_updates",
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info(f"Scheduler started — updates every {UPDATE_INTERVAL_HOURS}h")

    # 3. Health-check server (non-blocking background task)
    asyncio.create_task(start_health_server())

    # 4. Start bot
    await bot.start()
    me = await bot.get_me()
    logger.info(f"🤖 Bot started: @{me.username} ({me.id})")

    # 5. Block until killed
    await idle()

    # 6. Graceful shutdown
    scheduler.shutdown(wait=False)
    await close_db()
    await bot.stop()
    logger.info("Bot stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
