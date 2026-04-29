import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any

from aiohttp import web
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

# Correct import for simple-justwatch-python-api 0.13+
from simplejustwatchapi.justwatch import JustWatch

import database as db

load_dotenv()

# ---------- Configuration ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Missing BOT_TOKEN environment variable")

CHAT_ID = os.getenv("CHAT_ID")          # optional: single channel/group ID
UPDATE_INTERVAL_HOURS = int(os.getenv("UPDATE_INTERVAL_HOURS", "6"))
PORT = int(os.getenv("PORT", "8080"))
JUSTWATCH_COUNTRY = os.getenv("JUSTWATCH_COUNTRY", "US")
JUSTWATCH_LANGUAGE = os.getenv("JUSTWATCH_LANGUAGE", "en")

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- JustWatch Client ----------
justwatch_client = JustWatch(country=JUSTWATCH_COUNTRY, language=JUSTWATCH_LANGUAGE)

# ---------- JustWatch Helpers ----------
async def get_new_releases(days_back: int = 14) -> List[Dict[str, Any]]:
    """
    Fetch movies and TV series that were released within the last 'days_back' days.
    Uses JustWatch search for popular items (empty query) and filters by release date.
    """
    cutoff_date = datetime.now() - timedelta(days=days_back)
    new_items = []

    # For both movies (content_type="movie") and TV shows (content_type="show")
    for content_type in ["movie", "show"]:
        try:
            # Run synchronous JustWatch search in a thread pool
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda ct=content_type: justwatch_client.search_for_item(
                    query="",                      # empty = popular / trending
                    content_types=[ct],
                    page_size=30,
                    # Optionally add other filters like `release_year_from` if needed
                )
            )

            items = results.get("items", [])
            for item in items:
                # Extract release date (field names may vary – adjust if needed)
                if content_type == "movie":
                    release_date_str = item.get("original_release_date") or item.get("release_date")
                else:  # show
                    release_date_str = item.get("first_air_date")

                if not release_date_str:
                    continue

                try:
                    release_date = datetime.strptime(release_date_str, "%Y-%m-%d")
                    if release_date < cutoff_date:
                        continue
                except (ValueError, TypeError):
                    continue

                item_id = f"{content_type}_{item.get('id')}"
                if not db.is_item_sent(item_id):
                    # Build a clean dict for messaging
                    offers = []
                    for offer in item.get("offers", []):
                        package = offer.get("package", {}).get("package_name")
                        if package and package not in offers:
                            offers.append(package)

                    new_items.append({
                        "type": content_type,
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "release_date": release_date_str,
                        "overview": item.get("short_description", "No description available."),
                        "poster_url": item.get("poster_url"),
                        "offers": offers[:5]  # max 5 streaming services
                    })
                    db.mark_item_sent(item_id)

        except Exception as e:
            logger.error(f"Error fetching {content_type}s from JustWatch: {e}")

    return new_items

def format_item_message(item: Dict[str, Any]) -> str:
    """Create a nice Telegram message for a movie or TV series."""
    media_type = "🎬 Movie" if item["type"] == "movie" else "📺 TV Series"
    title = item["title"]
    release_date = item["release_date"]
    year = release_date[:4] if release_date else "?"
    overview = item["overview"]
    if len(overview) > 500:
        overview = overview[:497] + "..."

    platforms_text = ", ".join(item.get("offers", [])) if item.get("offers") else "Check JustWatch for availability"

    message = (
        f"*{media_type}: {title} ({year})*\n"
        f"📅 *Release:* {release_date}\n"
        f"📺 *Watch on:* {platforms_text}\n\n"
        f"{overview}\n\n"
        f"[More info on JustWatch](https://www.justwatch.com/{JUSTWATCH_COUNTRY}/{item['type']}/{item['id']})"
    )
    return message

# ---------- Broadcast Helpers ----------
async def send_to_subscribers(context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode="Markdown"):
    """Send a message to all subscribers + CHAT_ID if set."""
    chat_ids = set()
    if CHAT_ID:
        for cid in str(CHAT_ID).split(","):
            chat_ids.add(int(cid.strip()))
    else:
        chat_ids.update(db.get_subscribers())

    if not chat_ids:
        logger.info("No subscribers and no CHAT_ID. Nothing to send.")
        return

    for cid in chat_ids:
        try:
            await context.bot.send_message(chat_id=cid, text=text, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Failed to send to {cid}: {e}")

async def check_updates(context: ContextTypes.DEFAULT_TYPE):
    """Job that fetches new items and broadcasts them."""
    logger.info("Checking for new OTT releases via JustWatch...")
    try:
        new_items = await get_new_releases(days_back=14)  # last 14 days
        if not new_items:
            logger.info("No new releases found.")
            return

        for item in new_items:
            msg = format_item_message(item)
            await send_to_subscribers(context, msg)

        logger.info(f"Sent {len(new_items)} new releases.")
    except Exception as e:
        logger.exception("Error in check_updates")

# ---------- Bot Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 Welcome to OTT Updates Bot!\n\n"
        "I fetch new movies and TV series added to streaming platforms (via JustWatch).\n"
        "Use /subscribe to receive updates.\n"
        "Use /unsubscribe to stop.\n"
        "Use /help for more info."
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if CHAT_ID:
        await update.message.reply_text(
            "This bot is configured to broadcast to a fixed channel only. "
            "Individual subscriptions are disabled."
        )
        return
    db.add_subscriber(chat_id)
    await update.message.reply_text("✅ Subscribed! You'll receive OTT updates.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if CHAT_ID:
        await update.message.reply_text("Individual subscriptions disabled.")
        return
    db.remove_subscriber(chat_id)
    await update.message.reply_text("❌ Unsubscribed.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/start - Welcome\n"
        "/subscribe - Get updates\n"
        "/unsubscribe - Stop updates\n"
        "/help - This message\n\n"
        f"Bot checks for new releases every {UPDATE_INTERVAL_HOURS} hours."
    )

# ---------- HTTP Health Check Server ----------
async def health_check(request):
    return web.Response(text="OK")

async def run_web_server():
    app = web.Application()
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health check server running on port {PORT}")
    # Keep alive forever
    await asyncio.Event().wait()

# ---------- Main ----------
async def main():
    db.init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("help", help_command))

    await application.bot.set_my_commands([
        BotCommand("start", "Welcome"),
        BotCommand("subscribe", "Receive OTT updates"),
        BotCommand("unsubscribe", "Stop updates"),
        BotCommand("help", "Show help"),
    ])

    # Schedule periodic updates
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            check_updates,
            interval=UPDATE_INTERVAL_HOURS * 3600,
            first=10
        )
        logger.info(f"Scheduled updates every {UPDATE_INTERVAL_HOURS} hours")
    else:
        logger.warning("JobQueue not available")

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    web_task = asyncio.create_task(run_web_server())

    try:
        await asyncio.gather(application.updater.stop(), web_task)
    except KeyboardInterrupt:
        pass
    finally:
        await application.updater.stop()
        await application.stop()

if __name__ == "__main__":
    asyncio.run(main())
