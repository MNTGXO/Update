import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from aiohttp import web
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

# ---------- Configuration ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logging.error("Missing BOT_TOKEN environment variable")
    sys.exit(1)

CHAT_ID = os.getenv("CHAT_ID")
UPDATE_INTERVAL_HOURS = int(os.getenv("UPDATE_INTERVAL_HOURS", "6"))
PORT = int(os.getenv("PORT", "8080"))
JUSTWATCH_COUNTRY = os.getenv("JUSTWATCH_COUNTRY", "US")
JUSTWATCH_LANGUAGE = os.getenv("JUSTWATCH_LANGUAGE", "en")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Database setup ----------
import sqlite3
from typing import List

DB_PATH = "subscriptions.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id INTEGER PRIMARY KEY
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_items (
            item_id TEXT PRIMARY KEY,
            sent_at TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def add_subscriber(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()

def remove_subscriber(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def get_subscribers() -> List[int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM subscribers")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def is_item_sent(item_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM sent_items WHERE item_id = ?", (item_id,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def mark_item_sent(item_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO sent_items (item_id, sent_at) VALUES (?, ?)",
        (item_id, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

# ---------- JustWatch API Helpers ----------
async def get_new_releases(days_back: int = 7) -> List[Dict[str, Any]]:
    """
    Fetch movies and TV series using JustWatch's search function and filter by release date.
    Uses a try/except pattern to handle potential API differences.
    """
    cutoff_date = datetime.now() - timedelta(days=days_back)
    new_items = []

    # Try the official 'simple-justwatch-python-api' approach first
    try:
        from simplejustwatchapi.justwatch import search as justwatch_search
        
        for content_type in ["movie", "show"]:
            try:
                loop = asyncio.get_event_loop()
                search_query = "" if content_type == "movie" else ""
                results = await loop.run_in_executor(
                    None,
                    lambda: justwatch_search(
                        title=search_query,
                        country=JUSTWATCH_COUNTRY,
                        language=JUSTWATCH_LANGUAGE,
                        count=30
                    )
                )
                
                for item in results:
                    # Filter by content type based on object_type attribute
                    item_type = getattr(item, 'object_type', '').lower()
                    if content_type == "movie" and item_type != "movie":
                        continue
                    if content_type == "show" and item_type not in ["show", "tv_show"]:
                        continue
                    
                    release_date = getattr(item, 'release_date', None)
                    if not release_date:
                        continue
                    
                    try:
                        rel_date = datetime.strptime(release_date, "%Y-%m-%d")
                        if rel_date < cutoff_date:
                            continue
                    except:
                        continue
                    
                    item_id = f"{content_type}_{getattr(item, 'object_id', '')}"
                    if not is_item_sent(item_id):
                        # Extract platform names from offers
                        platforms = []
                        for offer in getattr(item, 'offers', []):
                            platform_name = getattr(offer, 'name', None)
                            if platform_name and platform_name not in platforms:
                                platforms.append(platform_name)
                        
                        new_items.append({
                            "type": content_type,
                            "id": getattr(item, 'object_id', ''),
                            "title": getattr(item, 'title', 'Unknown Title'),
                            "release_date": release_date,
                            "overview": getattr(item, 'short_description', 'No description available.'),
                            "poster_url": getattr(item, 'poster', None),
                            "offers": platforms[:5]  # Max 5 platforms
                        })
                        mark_item_sent(item_id)
            except Exception as e:
                logger.error(f"Error fetching {content_type}s with simple-justwatch-python-api: {e}")
                
    except ImportError:
        logger.info("simple-justwatch-python-api not found, trying alternative import...")
        
        # Alternative approach: Try 'justwatch' library (different package)
        try:
            from justwatch import JustWatch
            justwatch = JustWatch(country=JUSTWATCH_COUNTRY)
            
            for content_type in ["movie", "show"]:
                try:
                    results = justwatch.search_for_item(
                        query="",
                        content_types=[content_type],
                        page_size=30
                    )
                    
                    items = results.get("items", [])
                    for item in items:
                        release_date = item.get("original_release_date") or item.get("release_date")
                        if not release_date:
                            continue
                        
                        try:
                            rel_date = datetime.strptime(release_date, "%Y-%m-%d")
                            if rel_date < cutoff_date:
                                continue
                        except:
                            continue
                        
                        item_id = f"{content_type}_{item.get('id')}"
                        if not is_item_sent(item_id):
                            # Extract platform names from offers
                            platforms = []
                            for offer in item.get("offers", []):
                                package = offer.get("package", {}).get("package_name")
                                if package and package not in platforms:
                                    platforms.append(package)
                            
                            new_items.append({
                                "type": content_type,
                                "id": item.get("id"),
                                "title": item.get("title", "Unknown Title"),
                                "release_date": release_date,
                                "overview": item.get("short_description", "No description available."),
                                "poster_url": item.get("poster_url"),
                                "offers": platforms[:5]
                            })
                            mark_item_sent(item_id)
                except Exception as e:
                    logger.error(f"Error fetching {content_type}s with justwatch library: {e}")
                    
        except ImportError:
            logger.error("No JustWatch library found. Please install simple-justwatch-python-api or justwatch.")
    
    return new_items

def format_item_message(item: Dict[str, Any]) -> str:
    """Create a nice Telegram message for a movie or TV series."""
    media_type = "🎬 Movie" if item["type"] == "movie" else "📺 TV Series"
    title = item["title"]
    release_date = item["release_date"]
    year = release_date[:4] if release_date and len(release_date) >= 4 else "?"
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
        chat_ids.update(get_subscribers())

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
        new_items = await get_new_releases(days_back=7)  # Last 7 days
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
    add_subscriber(chat_id)
    await update.message.reply_text("✅ Subscribed! You'll receive OTT updates.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if CHAT_ID:
        await update.message.reply_text("Individual subscriptions disabled.")
        return
    remove_subscriber(chat_id)
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
    await asyncio.Event().wait()  # Keep alive forever

# ---------- Main ----------
async def main():
    init_db()

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
