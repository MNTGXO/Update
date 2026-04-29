from pyrogram import Client, filters
from pyrogram.types import Message

@Client.on_message(filters.command("about"))
async def about(client: Client, message: Message):
    await message.reply_text(
        "🤖 *OTT Updates Bot*\n\n"
        "Uses JustWatch data. No API key required.\n\n"
        "Data from [JustWatch](https://justwatch.com).",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
