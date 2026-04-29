from pyrogram import Client, filters
from pyrogram.types import Message
from config import CHAT_ID
from database import remove_subscriber

@Client.on_message(filters.command("unsubscribe"))
async def unsubscribe(client: Client, message: Message):
    if CHAT_ID:
        await message.reply_text("Individual subscriptions disabled.")
        return
    remove_subscriber(message.chat.id)
    await message.reply_text("❌ Unsubscribed.")
