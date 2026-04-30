from pyrogram import Client, filters
from pyrogram.types import Message
from config import JUSTWATCH_COUNTRY

PLATFORMS_TEXT = (
    "📡 **Supported OTT Platforms**\n\n"
    "🔴 Netflix\n"
    "🔵 Amazon Prime Video\n"
    "🟣 Disney+\n"
    "🟠 Hotstar\n"
    "⚪ Apple TV+\n"
    "🔵 HBO Max / Max\n"
    "🟢 Hulu\n"
    "🟡 Peacock\n"
    "🔴 Paramount+\n"
    "🟠 SonyLIV\n"
    "🟢 ZEE5\n"
    "⚫ MX Player\n"
    "🟣 Crunchyroll\n"
    "⚪ MUBI\n\n"
    "📍 **Your region:** `{country}`\n\n"
    "_Availability varies by region. "
    "The bot only notifies you about content available in your configured country._"
)


@Client.on_message(filters.command("platforms"))
async def platforms(client: Client, message: Message):
    await message.reply_text(
        PLATFORMS_TEXT.format(country=JUSTWATCH_COUNTRY),
        disable_web_page_preview=True,
    )
