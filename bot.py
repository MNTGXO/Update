import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

from aiohttp import web
from dotenv import load_dotenv
from pyrogram import Client, idle, enums
from pyrogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import (
    init_db, close_db,
    get_auto_send_subscribers, remove_subscriber,
    is_item_sent, mark_item_sent,
)
from utils import get_new_releases, format_item_message, format_item_keyboard
from config import (
    UPDATE_INTERVAL_HOURS, CHAT_ID, MONGO_URI, ADMIN_ID,
    JUSTWATCH_COUNTRY, TMDB_API_KEY, MONGO_DB_NAME,
)

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────
API_ID    = os.getenv("API_ID")
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT      = int(os.getenv("PORT", "8080"))

missing = [k for k, v in {
    "BOT_TOKEN": BOT_TOKEN,
    "API_ID":    API_ID,
    "API_HASH":  API_HASH,
    "MONGO_URI": MONGO_URI,
}.items() if not v]
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

# ─── Globals set inside main() ────────────────────────────────────────────────
# bot is NOT created at module level — doing so captures the wrong event loop
# and causes "Future attached to a different loop" on Pyrogram's SQLite storage.
bot: Client | None = None
scheduler = AsyncIOScheduler(timezone="UTC")
_bad_targets: set[int | str] = set()


# ─── Scheduled job ────────────────────────────────────────────────────────────
async def send_updates() -> None:
    """Fetch new OTT releases and push them to all subscribers / channels."""
    logger.info("⏰ Scheduled job: checking for new releases …")

    # Collect target chat IDs
    chat_ids: set[int | str] = set()
    if CHAT_ID:
        for raw in str(CHAT_ID).split(","):
            cid = raw.strip()
            if not cid:
                continue
            if cid.startswith("@"):
                chat_ids.add(cid)
            else:
                try:
                    chat_ids.add(int(cid))
                except ValueError:
                    logger.warning(f"Invalid CHAT_ID value skipped: {cid}")

    chat_ids.update(await get_auto_send_subscribers())
    chat_ids = {cid for cid in chat_ids if cid not in _bad_targets}

    if not chat_ids:
        logger.info("No subscribers or CHAT_ID configured — skipping send.")
        return

    all_items = await get_new_releases(days_back=7)
    if not all_items:
        logger.info("No new releases found this cycle.")
        return

    # ── Dedup: skip items already sent ────────────────────────────────────────
    new_items = []
    for item in all_items:
        item_id = str(item.get("id") or item.get("tmdb_id") or item.get("title", ""))
        if not item_id:
            continue
        if await is_item_sent(item_id):
            logger.debug(f"Skipping already-sent item: {item.get('title')} ({item_id})")
            continue
        new_items.append((item_id, item))

    if not new_items:
        logger.info("All releases already sent — nothing new.")
        return

    logger.info(f"Found {len(new_items)} new item(s) to send.")

    sent_total = 0
    for cid in chat_ids:
        for item_id, item in new_items[:10]:
            try:
                poster = item.get("poster", "")
                text   = format_item_message(item)
                kb     = format_item_keyboard(item)

                if poster:
                    try:
                        await bot.send_photo(
                            cid, poster, caption=text,
                            parse_mode=enums.ParseMode.HTML,
                            reply_markup=kb,
                        )
                    except Exception as photo_exc:
                        logger.warning(f"Photo send failed for {cid}, falling back: {photo_exc}")
                        await bot.send_message(
                            cid, text,
                            parse_mode=enums.ParseMode.HTML,
                            disable_web_page_preview=False,
                            reply_markup=kb,
                        )
                else:
                    await bot.send_message(
                        cid, text,
                        parse_mode=enums.ParseMode.HTML,
                        disable_web_page_preview=False,
                        reply_markup=kb,
                    )

                sent_total += 1
                await asyncio.sleep(0.5)          # stay inside Telegram rate limits

            except Exception as exc:
                logger.warning(f"Failed to send to {cid}: {exc}")
                if "Peer id invalid" in str(exc):
                    _bad_targets.add(cid)
                    if isinstance(cid, int):
                        await remove_subscriber(cid)
                    logger.warning(f"Disabled invalid target: {cid}")
                    break

    # Mark every successfully-processed item as sent (once, not per chat)
    for item_id, item in new_items[:10]:
        await mark_item_sent(item_id, title=item.get("title", ""))

    logger.info(f"✅ Sent {sent_total} message(s) across {len(chat_ids)} chat(s).")


# ─── Health-check HTTP server ─────────────────────────────────────────────────
async def _health(request):
    return web.Response(text="OK")


async def start_health_server() -> None:
    app_web = web.Application()
    app_web.router.add_get("/",       _health)
    app_web.router.add_get("/health", _health)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health-check server listening on :{PORT}")


def _loop_exception_handler(loop, context):
    msg = context.get("message", "Unhandled asyncio exception")
    exc = context.get("exception")
    if exc:
        logger.error(f"{msg}: {exc}", exc_info=exc)
    else:
        logger.error(msg)


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main() -> None:
    global bot

    bot_started       = False
    scheduler_started = False

    try:
        # 1. Connect MongoDB
        await init_db()

        # 2. Create the Pyrogram Client HERE, inside the running event loop.
        #    in_memory=True avoids SQLite entirely — correct for Koyeb/Docker
        #    where there is no persistent writable filesystem.
        bot = Client(
            "ott_bot",
            api_id=int(API_ID),
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            plugins=dict(root="plugins"),
            parse_mode=enums.ParseMode.HTML,
            in_memory=True,          # ← eliminates the "different loop" crash
        )

        # 3. Schedule periodic updates
        first_run = datetime.utcnow() + timedelta(minutes=10)
        scheduler.add_job(
            send_updates,
            "interval",
            hours=UPDATE_INTERVAL_HOURS,
            next_run_time=first_run,
            id="send_updates",
            misfire_grace_time=300,
        )
        scheduler.start()
        scheduler_started = True
        logger.info(f"Scheduler started — updates every {UPDATE_INTERVAL_HOURS}h")

        # 4. Health-check server (background)
        asyncio.create_task(start_health_server())

        # 5. Start bot
        await bot.start()
        bot_started = True

        # Register command hints
        try:
            await bot.set_bot_commands([
                BotCommand("start",       "Start the bot"),
                BotCommand("help",        "Show help"),
                BotCommand("subscribe",   "Subscribe to auto updates"),
                BotCommand("unsubscribe", "Unsubscribe from updates"),
                BotCommand("latest",      "Get latest releases now"),
                BotCommand("platforms",   "Show supported platforms"),
                BotCommand("stats",       "Show bot statistics"),
                BotCommand("about",       "About this bot"),
            ])
        except Exception as exc:
            logger.warning(f"Failed to register bot commands: {exc}")

        me = await bot.get_me()
        logger.info(f"🤖 Bot started: @{me.username} ({me.id})")

        # Notify admin on startup
        if ADMIN_ID:
            source = "TMDB API ✅" if TMDB_API_KEY else "JustWatch GraphQL"
            try:
                await bot.send_message(
                    int(ADMIN_ID),
                    f"🟢 <b>Bot Restarted Successfully!</b>\n\n"
                    f"🤖 <b>Username:</b> @{me.username}\n"
                    f"🆔 <b>Bot ID:</b> <code>{me.id}</code>\n"
                    f"🌍 <b>Region:</b> <code>{JUSTWATCH_COUNTRY}</code>\n"
                    f"🗃 <b>Database:</b> <code>{MONGO_DB_NAME}</code>\n"
                    f"📡 <b>Data source:</b> {source}\n"
                    f"🔄 <b>Update interval:</b> every {UPDATE_INTERVAL_HOURS}h\n\n"
                    f"✅ All systems operational.",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception as e:
                logger.warning(f"Could not notify admin: {e}")

        # 6. Block until killed
        await idle()

    finally:
        if scheduler_started:
            scheduler.shutdown(wait=False)
        await close_db()
        if bot_started and bot is not None:
            try:
                await bot.stop()
            except Exception as exc:
                logger.warning(f"Ignored shutdown race: {exc}")
        logger.info("Bot stopped cleanly.")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(_loop_exception_handler)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
