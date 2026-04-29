from pyrogram import Client, filters
from pyrogram.types import Message

@Client.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text(
        "🎬 *OTT Updates Bot*\n\n"
        "/subscribe – Get updates\n"
        "/unsubscribe – Stop\n"
        "/latest – Manual check\n"
        "/platforms – Streaming services\n"
        "/stats – Bot stats\n"
        "/about – Info\n"
        "/help – Help",
        parse_mode="Markdown"
    )
