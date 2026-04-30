import time
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from config import BOT_START_TIME, UPDATE_INTERVAL_HOURS, JUSTWATCH_COUNTRY, TMDB_API_KEY, MONGO_DB_NAME
from database import get_subscriber_count, get_sent_count


@Client.on_message(filters.command("stats"))
async def stats(client: Client, message: Message):
    subs     = await get_subscriber_count()
    notified = await get_sent_count()
    uptime   = int(time.time() - BOT_START_TIME)

    days,    rem  = divmod(uptime, 86400)
    hours,   rem  = divmod(rem, 3600)
    minutes, _    = divmod(rem, 60)

    source = "TMDB API ✅" if TMDB_API_KEY else "JustWatch GraphQL"

    await message.reply_text(
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Subscribers: <b>{subs}</b>\n"
        f"📬 Releases sent: <b>{notified}</b>\n"
        f"⏱ Uptime: <b>{days}d {hours}h {minutes}m</b>\n"
        f"🔄 Check interval: <b>every {UPDATE_INTERVAL_HOURS}h</b>\n"
        f"🌍 Region: <b>{JUSTWATCH_COUNTRY}</b>\n"
        f"🗃 Database: <b>MongoDB ({MONGO_DB_NAME})</b>\n"
        f"📡 Data source: <b>{source}</b>",
        parse_mode=enums.ParseMode.HTML,
    )
