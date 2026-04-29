import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any

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

ADMIN_ID = os.getenv("ADMIN_ID")  # optional, numeric Telegram user ID
CHAT_ID = os.getenv("CHAT_ID")    # optional fixed channel/group
UPDATE_INTERVAL_HOURS = int(os.getenv("UPDATE_INTERVAL_HOURS", "6"))
PORT = int(os.getenv("PORT", "8080"))
JUSTWATCH_COUNTRY = os.getenv("JUSTWATCH_COUNTRY", "US")
JUSTWATCH_LANGUAGE = os.getenv("JUSTWATCH_LANGUAGE", "en")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Bot start time for uptime stats ----------
BOT_START_TIME = time.time()

# ---------- Database setup ----------
import sqlite3

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
    cutoff_date = datetime.now() - timedelta(days=days_back)
    new_items = []

    try:
        from simplejustwatchapi.justwatch import search as justwatch_search
        
        for content_type in ["movie", "show"]:
            try:
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None,
                    lambda: justwatch_search(
                        title="",
                        country=JUSTWATCH_COUNTRY,
                        language=JUSTWATCH_LANGUAGE,
                        count=30
                    )
                )
                
                for item in results:
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
                            "offers": platforms[:5]
                        })
                        mark_item_sent(item_id)
            except Exception as e:
                logger.error(f"Error fetching {content_type}s: {e}")
    except ImportError:
        logger.error("simple-justwatch-python-api not installed")
    
    return new_items

def format_item_message(item: Dict[str, Any]) -> str:
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
    logger.info("Checking for new OTT releases via JustWatch...")
    try:
        new_items = await get_new_releases(days_back=7)
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
        "🎬 *Welcome to OTT Updates Bot!*\n\n"
        "I fetch new movies and TV series recently added to streaming platforms (via JustWatch).\n\n"
        "*/subscribe* – Get updates\n"
        "*/unsubscribe* – Stop updates\n"
        "*/latest* – Manually check for new releases\n"
        "*/platforms* – See supported streaming services\n"
        "*/stats* – Bot statistics\n"
        "*/about* – About this bot\n"
        "*/help* – Show this help\n\n"
        f"⏱️ Updates every {UPDATE_INTERVAL_HOURS} hours.",
        parse_mode="Markdown"
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

async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger a check for new releases."""
    await update.message.reply_text("🔍 Checking for latest releases... Please wait.")
    try:
        new_items = await get_new_releases(days_back=7)
        if not new_items:
            await update.message.reply_text("No new releases found in the last 7 days.")
            return
        
        # Send each new item to the user who requested
        for item in new_items:
            msg = format_item_message(item)
            await update.message.reply_text(msg, parse_mode="Markdown")
            await asyncio.sleep(0.5)  # avoid flooding
        
        await update.message.reply_text(f"✅ Found {len(new_items)} new releases.")
    except Exception as e:
        logger.exception("Error in /latest")
        await update.message.reply_text("❌ Failed to fetch releases. Please try again later.")

async def platforms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show a list of common streaming platforms tracked by JustWatch."""
    platform_list = (
        "🎬 *Supported Streaming Platforms (via JustWatch)*\n\n"
        "• Netflix\n"
        "• Amazon Prime Video\n"
        "• Disney+\n"
        "• Hulu\n"
        "• Apple TV+\n"
        "• HBO Max\n"
        "• Peacock\n"
        "• Paramount+\n"
        "• YouTube\n"
        "• Google Play Movies\n"
        "• Vudu\n"
        "• And many more...\n\n"
        "The bot shows availability based on your region (current: `{}`).".format(JUSTWATCH_COUNTRY)
    )
    await update.message.reply_text(platform_list, parse_mode="Markdown")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics."""
    sub_count = len(get_subscribers())
    uptime_seconds = int(time.time() - BOT_START_TIME)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
    
    stats_msg = (
        f"📊 *Bot Statistics*\n\n"
        f"👥 Subscribers: {sub_count}\n"
        f"⏱️ Uptime: {uptime_str}\n"
        f"🔄 Update interval: {UPDATE_INTERVAL_HOURS} hours\n"
        f"🌍 Region: {JUSTWATCH_COUNTRY}\n"
        f"💾 Database: SQLite (local)"
    )
    await update.message.reply_text(stats_msg, parse_mode="Markdown")

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """About this bot."""
    about_msg = (
        "🤖 *About OTT Updates Bot*\n\n"
        "This bot fetches newly released movies and TV series added to streaming platforms using JustWatch data.\n\n"
        "No API key required – uses JustWatch's public search.\n\n"
        "Developed with python-telegram-bot and deployed on Koyeb.\n\n"
        "Source code & support: [GitHub Repository](https://github.com/yourusername/telegram-justwatch-bot)\n\n"
        "Data provided by [JustWatch](https://www.justwatch.com)."
    )
    await update.message.reply_text(about_msg, parse_mode="Markdown", disable_web_page_preview=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help menu."""
    help_text = (
        "📖 *Available Commands*\n\n"
        "/start – Welcome & main menu\n"
        "/subscribe – Receive OTT updates\n"
        "/unsubscribe – Stop updates\n"
        "/latest – Manually fetch latest releases\n"
        "/platforms – Show supported streaming platforms\n"
        "/stats – Bot statistics\n"
        "/about – Information about this bot\n"
        "/help – Show this help\n\n"
        f"⏲️ Automatic updates every {UPDATE_INTERVAL_HOURS} hours."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ---------- Admin-only commands (if ADMIN_ID set) ----------
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to send a message to all subscribers."""
    if ADMIN_ID and update.effective_user.id != int(ADMIN_ID):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    
    message = " ".join(context.args)
    subscribers = get_subscribers()
    if not subscribers:
        await update.message.reply_text("No subscribers to broadcast to.")
        return
    
    success_count = 0
    for chat_id in subscribers:
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"📢 *Announcement*\n\n{message}", parse_mode="Markdown")
            success_count += 1
            await asyncio.sleep(0.1)  # small delay to avoid hitting limits
        except Exception as e:
            logger.error(f"Broadcast failed to {chat_id}: {e}")
    
    await update.message.reply_text(f"Broadcast sent to {success_count}/{len(subscribers)} subscribers.")

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
    await asyncio.Event().wait()

# ---------- Main ----------
async def main():
    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    # Add all command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("latest", latest))
    application.add_handler(CommandHandler("platforms", platforms))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("help", help_command))
    
    # Admin command (if ADMIN_ID provided)
    if ADMIN_ID:
        application.add_handler(CommandHandler("broadcast", broadcast))
    
    # Set bot commands for menu
    commands = [
        BotCommand("start", "Welcome & main menu"),
        BotCommand("subscribe", "Receive OTT updates"),
        BotCommand("unsubscribe", "Stop updates"),
        BotCommand("latest", "Manually fetch latest releases"),
        BotCommand("platforms", "Show supported streaming platforms"),
        BotCommand("stats", "Bot statistics"),
        BotCommand("about", "About this bot"),
        BotCommand("help", "Show help"),
    ]
    if ADMIN_ID:
        commands.append(BotCommand("broadcast", "Send message to all subscribers (admin only)"))
    
    await application.bot.set_my_commands(commands)
    
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
