from pyrogram import Client, filters, enums
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import JUSTWATCH_COUNTRY
from database import set_auto_send

WELCOME = (
    "🎬 <b>OTT Updates Bot</b>\n\n"
    "Use commands in PM to control your updates dynamically.\n\n"
    "• /subscribe\n• /unsubscribe\n• /latest\n• /autosend on|off\n• /platforms\n• /about\n• /help"
)

HELP = (
    "🆘 <b>Help</b>\n\n"
    "/start - Welcome\n"
    "/subscribe - Enable updates\n"
    "/unsubscribe - Disable updates\n"
    "/autosend on|off - Toggle scheduled messages\n"
    "/latest - Check latest now\n"
    "/platforms - Supported services\n"
    "/about - Bot info"
)

ABOUT = "🤖 <b>OTT Updates Bot</b>\nTracks OTT releases and sends updates."

PLATFORMS = (
    "📡 <b>Supported OTT Platforms</b>\n"
    "<i>Region: <code>{country}</code></i>\n\n"
    "Netflix, Prime Video, Disney+, Hotstar, Apple TV+, Max, Hulu, Peacock, Paramount+, SonyLIV, ZEE5, MX Player, Crunchyroll, MUBI, Starz"
)

KB = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Subscribe", callback_data="subscribe"), InlineKeyboardButton("❌ Unsubscribe", callback_data="unsubscribe")]])


@Client.on_message(filters.command("start") & filters.private)
async def start(client: Client, message: Message):
    await message.reply_text(WELCOME, parse_mode=enums.ParseMode.HTML, reply_markup=KB)


@Client.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    await message.reply_text(HELP, parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command("about") & filters.private)
async def about_cmd(client: Client, message: Message):
    await message.reply_text(ABOUT, parse_mode=enums.ParseMode.HTML)


@Client.on_callback_query(filters.regex("^about$"))
async def about_cb(client: Client, cb: CallbackQuery):
    await cb.answer()
    await cb.message.reply_text(ABOUT, parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command("platforms") & filters.private)
async def platforms(client: Client, message: Message):
    await message.reply_text(PLATFORMS.format(country=JUSTWATCH_COUNTRY), parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command("autosend") & filters.private)
async def autosend_cmd(client: Client, message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].lower() not in {"on", "off"}:
        await message.reply_text("Usage: /autosend on|off")
        return
    enabled = parts[1].lower() == "on"
    await set_auto_send(message.chat.id, enabled)
    await message.reply_text(f"✅ Auto-send {'enabled' if enabled else 'disabled'} for this chat.")
