from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

WELCOME = (
    "🎬 <b>OTT Updates Bot</b>\n\n"
    "Get notified the moment new movies or TV shows land on\n"
    "Netflix, Prime, Hotstar, Disney+, and 10+ other platforms.\n\n"
    "<b>Commands</b>\n"
    "• /subscribe — get automatic updates\n"
    "• /unsubscribe — stop updates\n"
    "• /latest — check right now\n"
    "• /platforms — supported platforms\n"
    "• /stats — bot statistics\n"
    "• /about — about this bot\n"
    "• /help — all commands"
)

KB = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("✅ Subscribe",   callback_data="subscribe"),
        InlineKeyboardButton("❌ Unsubscribe", callback_data="unsubscribe"),
    ],
    [
        InlineKeyboardButton("🔍 Latest now", callback_data="latest"),
        InlineKeyboardButton("ℹ️ About",      callback_data="about"),
    ],
])


@Client.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text(WELCOME, reply_markup=KB,
                             parse_mode=enums.ParseMode.HTML)
    
