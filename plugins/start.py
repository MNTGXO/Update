from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton


WELCOME = (
    "🎬 **OTT Updates Bot**\n\n"
    "Get notified whenever new movies or TV shows land on your favourite "
    "streaming platforms — Netflix, Prime, Hotstar, Disney+, and more.\n\n"
    "**Commands**\n"
    "• /subscribe — get automatic updates\n"
    "• /unsubscribe — stop updates\n"
    "• /latest — check right now\n"
    "• /platforms — supported platforms\n"
    "• /stats — bot statistics\n"
    "• /about — about this bot\n"
    "• /help — show this message"
)


@Client.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Subscribe", callback_data="subscribe"),
            InlineKeyboardButton("❌ Unsubscribe", callback_data="unsubscribe"),
        ],
        [
            InlineKeyboardButton("🔍 Latest now", callback_data="latest"),
            InlineKeyboardButton("ℹ️ About", callback_data="about"),
        ],
    ])
    await message.reply_text(WELCOME, reply_markup=kb)
