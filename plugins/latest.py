from pyrogram import Client, filters
from pyrogram.types import Message
import asyncio
from utils import get_new_releases, format_item_message

@Client.on_message(filters.command("latest"))
async def latest(client: Client, message: Message):
    status_msg = await message.reply_text("🔍 Checking...")
    items = await get_new_releases(days_back=7)
    if not items:
        await status_msg.edit_text("No new releases in the last 7 days.")
        return
    await status_msg.delete()
    for item in items:
        await message.reply_text(format_item_message(item), parse_mode="Markdown")
        await asyncio.sleep(0.5)
    await message.reply_text(f"✅ Found {len(items)} new releases.")
