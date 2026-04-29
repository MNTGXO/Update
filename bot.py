import asyncio
import logging
import os
import sys
import time
import threading
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

ADMIN_ID = os.getenv("ADMIN_ID")
CHAT_ID = os.getenv("CHAT_ID")
UPDATE_INTERVAL_HOURS = int(os.getenv("UPDATE_INTERVAL_HOURS", "6"))
PORT = int(os.getenv("PORT", "8080"))
JUSTWATCH_COUNTRY = os.getenv("JUSTWATCH_COUNTRY", "US")
JUSTWATCH_LANGUAGE = os.getenv("JUSTWATCH_LANGUAGE", "en")

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ---------- Bot start time ----------
BOT_START_TIME = time.time()

# ---------- Database setup ----------
import sqlite3

DB_PATH = "subscriptions.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS subscribers (chat_id INTEGER PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS sent_items (item_id TEXT PRIMARY KEY, sent_at TIMESTAMP)")
    conn.commit()
    conn.close()
    logger.info("Database initialized")

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
    c.execute("INSERT OR IGNORE INTO sent_items (item_id, sent_at) VALUES (?, ?)",
              (item_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ---------- JustWatch Helper ----------
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
                logger.info(f"Fetched {len(results)} items for {content_type}")
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
                            "offers": platforms[:5]
                        })
                        mark_item_sent(item_id)
            except Exception as e:
                logger.error(f"Error fetching {content_type}s: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"JustWatch import/usage error: {e}", exc_info=True)
    
    return new_items

def format_item_message(item: Dict[str, Any]) -> str:
    media_type = "🎬 Movie" if item["type"] == "movie" else "📺 TV Series"
    title = item["title"]
    release_date = item["release_date"]
    year = release_date[:4] if release_date and len(release_date) >= 4 else "?"
    overview = item["overview"]
    if len(overview) > 500:
        overview = overview[:497] + "..."
    platforms_text = ", ".join(item.get("offers", [])) if item.get("offers") else "Check JustWatch"
    return (
        f"*{media_type}: {title} ({year})*\n"
        f"📅 *Release:* {release_date}\n"
        f"📺 *Watch on:* {platforms_text}\n\n"
        f"{overview}\n\n"
        f"[More info](https://www.justwatch.com/{JUSTWATCH_COUNTRY}/{item['type']}/{item['id']})"
    )

async def send_to_subscribers(context: ContextTypes.DEFAULT_TYPE, text: str):
    chat_ids = set()
    if CHAT_ID:
        for cid in str(CHAT_ID).split(","):
            chat_ids.add(int(cid.strip()))
    else:
        chat_ids.update(get_subscribers())
    if not chat_ids:
        return
    for cid in chat_ids:
        try:
            await context.bot.send_message(chat_id=cid, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send to {cid}: {e}")

async def check_updates(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Checking for new OTT releases...")
    try:
        new_items = await get_new_releases(days_back=7)
        if not new_items:
            logger.info("No new releases found.")
            return
        for item in new_items:
            await send_to_subscribers(context, format_item_message(item))
        logger.info(f"Sent {len(new_items)} new releases.")
    except Exception as e:
        logger.exception("Error in check_updates")

# ---------- Command Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Start command from {update.effective_user.id}")
    await update.message.reply_text(
        "🎬 *OTT Updates Bot*\n\n"
        "/subscribe – Get updates\n"
        "/unsubscribe – Stop\n"
        "/latest – Manual check\n"
        "/platforms – Streaming services\n"
        "/stats – Bot stats\n"
        "/about – Info\n"
        "/help – This help",
        parse_mode="Markdown"
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if CHAT_ID:
        await update.message.reply_text("Individual subscriptions disabled.")
        return
    add_subscriber(update.effective_chat.id)
    await update.message.reply_text("✅ Subscribed!")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if CHAT_ID:
        await update.message.reply_text("Individual subscriptions disabled.")
        return
    remove_subscriber(update.effective_chat.id)
    await update.message.reply_text("❌ Unsubscribed.")

async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Checking...")
    try:
        items = await get_new_releases(days_back=7)
        if not items:
            await update.message.reply_text("No new releases (last 7 days).")
            return
        for item in items:
            await update.message.reply_text(format_item_message(item), parse_mode="Markdown")
            await asyncio.sleep(0.5)
        await update.message.reply_text(f"✅ {len(items)} new releases.")
    except Exception as e:
        logger.exception("Error in /latest")
        await update.message.reply_text("❌ Error fetching releases.")

async def platforms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🎬 *Streaming platforms* (region: {JUSTWATCH_COUNTRY})\n\nNetflix, Prime, Disney+, Hulu, Apple TV+, HBO Max, Peacock, Paramount+, and more.", parse_mode="Markdown")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sub_count = len(get_subscribers())
    uptime = int(time.time() - BOT_START_TIME)
    days, rem = divmod(uptime, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    await update.message.reply_text(
        f"📊 *Bot Stats*\n\n👥 Subscribers: {sub_count}\n⏱️ Uptime: {days}d {hours}h {minutes}m\n🔄 Interval: {UPDATE_INTERVAL_HOURS}h\n🌍 Region: {JUSTWATCH_COUNTRY}",
        parse_mode="Markdown"
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 *OTT Updates Bot*\n\nUses JustWatch data. No API key required.\n\nData from [JustWatch](https://justwatch.com).", parse_mode="Markdown", disable_web_page_preview=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and update.effective_user.id != int(ADMIN_ID):
        await update.message.reply_text("Unauthorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    msg = " ".join(context.args)
    subs = get_subscribers()
    if not subs:
        await update.message.reply_text("No subscribers.")
        return
    success = 0
    for cid in subs:
        try:
            await context.bot.send_message(chat_id=cid, text=f"📢 *Announcement*\n\n{msg}", parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Broadcast fail {cid}: {e}")
    await update.message.reply_text(f"Sent to {success}/{len(subs)} subscribers.")

# ---------- Health Check Server (runs in separate thread) ----------
def run_health_server():
    app = web.Application()
    async def health_check(request):
        return web.Response(text="OK")
    app.router.add_get("/health", health_check)
    web.run_app(app, host="0.0.0.0", port=PORT)

# ---------- Main ----------
async def main():
    init_db()
    
    # Start health check server in a background thread
    thread = threading.Thread(target=run_health_server, daemon=True)
    thread.start()
    logger.info(f"Health check server running on port {PORT}")
    
    # Create bot application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("latest", latest))
    application.add_handler(CommandHandler("platforms", platforms))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("help", help_command))
    if ADMIN_ID:
        application.add_handler(CommandHandler("broadcast", broadcast))
    
    # Set bot commands menu
    commands = [
        BotCommand("start", "Welcome"),
        BotCommand("subscribe", "Get updates"),
        BotCommand("unsubscribe", "Stop updates"),
        BotCommand("latest", "Manual check"),
        BotCommand("platforms", "Streaming platforms"),
        BotCommand("stats", "Bot stats"),
        BotCommand("about", "About"),
        BotCommand("help", "Help"),
    ]
    if ADMIN_ID:
        commands.append(BotCommand("broadcast", "Admin broadcast"))
    await application.bot.set_my_commands(commands)
    
    # Schedule periodic updates
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(check_updates, interval=UPDATE_INTERVAL_HOURS * 3600, first=10)
        logger.info(f"Scheduled updates every {UPDATE_INTERVAL_HOURS} hours")
    
    # Start polling (blocking)
    logger.info("Starting bot polling...")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
