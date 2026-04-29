from pyrogram import Client, filters
from pyrogram.types import Message
import time
import os
from database import get_subscribers

BOT_START_TIME = time.time()
UPDATE_INTERVAL_HOURS = int(os.getenv("UPDATE_INTERVAL_HOURS", "6"))

@Client.on_message(filters.command("stats"))
async def stats(client: Client, message: Message):
    sub_count = len(get_subscribers())
    uptime = int(time.time() - BOT_START_TIME)
    d, r = divmod(uptime, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    await message.reply_text(
        f"📊 *Stats*\n\n"
        f"👥 Subscribers: {sub_count}\n"
        f"⏱️ Uptime: {d}d {h}h {m}m\n"
        f"🔄 Interval: {UPDATE_INTERVAL_HOURS}h",
        parse_mode="Markdown"
    )
