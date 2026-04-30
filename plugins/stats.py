import time
from pyrogram import Client, filters
from pyrogram.types import Message
from config import BOT_START_TIME, UPDATE_INTERVAL_HOURS, JUSTWATCH_COUNTRY, TMDB_API_KEY
from database import get_subscriber_count, get_sent_count


@Client.on_message(filters.command("stats"))
async def stats(client: Client, message: Message):
    subs     = get_subscriber_count()
    notified = get_sent_count()
    uptime   = int(time.time() - BOT_START_TIME)

    days,    rem  = divmod(uptime, 86400)
    hours,   rem  = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    data_source = "TMDB API" if TMDB_API_KEY else "JustWatch (fallback)"

    await message.reply_text(
        "📊 **Bot Statistics**\n\n"
        f"👥 Subscribers: **{subs}**\n"
        f"📬 Releases notified: **{notified}**\n"
        f"⏱ Uptime: **{days}d {hours}h {minutes}m**\n"
        f"🔄 Check interval: **every {UPDATE_INTERVAL_HOURS}h**\n"
        f"🌍 Region: **{JUSTWATCH_COUNTRY}**\n"
        f"🗃 Data source: **{data_source}**"
    )
