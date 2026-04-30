from pyrogram import Client, filters, enums
from pyrogram.types import Message
from config import JUSTWATCH_COUNTRY

TEXT = (
    "📡 <b>Supported OTT Platforms</b>\n"
    "<i>Region: <code>{country}</code></i>\n\n"
    "🔴 Netflix\n"
    "🔵 Amazon Prime Video\n"
    "🟣 Disney+\n"
    "🟠 JioCinema / Hotstar\n"
    "⚪ Apple TV+\n"
    "🔵 Max (HBO Max)\n"
    "🟢 Hulu\n"
    "🟡 Peacock\n"
    "🔴 Paramount+\n"
    "🟠 SonyLIV\n"
    "🟢 ZEE5\n"
    "⚫ MX Player\n"
    "🟣 Crunchyroll\n"
    "⚪ MUBI\n"
    "🟤 Starz\n\n"
    "<i>Availability depends on your configured region.\n"
    "Only content streamable in your region is shown.</i>"
)


@Client.on_message(filters.command("platforms"))
async def platforms(client: Client, message: Message):
    await message.reply_text(TEXT.format(country=JUSTWATCH_COUNTRY),
                             parse_mode=enums.ParseMode.HTML)
