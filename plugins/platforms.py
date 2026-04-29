from pyrogram import Client, filters
from pyrogram.types import Message
from config import JUSTWATCH_COUNTRY

@Client.on_message(filters.command("platforms"))
async def platforms(client: Client, message: Message):
    await message.reply_text(
        f"🎬 *Streaming platforms* (region: {JUSTWATCH_COUNTRY})\n\n"
        "Netflix, Prime, Disney+, Hulu, Apple TV+, HBO Max, Peacock, Paramount+, and more.",
        parse_mode="Markdown"
    )
