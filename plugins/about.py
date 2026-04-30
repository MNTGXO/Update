from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery


ABOUT_TEXT = (
    "🤖 **OTT Updates Bot**\n\n"
    "This bot automatically tracks new movies and TV shows added to major OTT "
    "platforms and notifies you as soon as they are available.\n\n"
    "**Data sources**\n"
    "• [TMDB](https://www.themoviedb.org/) — primary (free API key required)\n"
    "• [JustWatch](https://www.justwatch.com/) — fallback (no key needed)\n\n"
    "**Features**\n"
    "✅ Auto-notifications on a configurable schedule\n"
    "✅ Movie posters\n"
    "✅ TMDB ratings & genres\n"
    "✅ Direct watch links\n"
    "✅ Multi-region support\n"
    "✅ Channel broadcasting mode\n\n"
    "Built with [Pyrogram](https://pyrogram.org/) 🐍"
)


@Client.on_message(filters.command("about"))
async def about_cmd(client: Client, message: Message):
    await message.reply_text(ABOUT_TEXT, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex("^about$"))
async def about_cb(client: Client, cb: CallbackQuery):
    await cb.answer()
    await cb.message.reply_text(ABOUT_TEXT, disable_web_page_preview=True)
