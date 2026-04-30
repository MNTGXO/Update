from pyrogram import Client, filters, enums
from pyrogram.types import Message, CallbackQuery

ABOUT = (
    "🤖 <b>OTT Updates Bot</b>\n\n"
    "Tracks new movies and TV shows added to major streaming platforms "
    "and notifies you automatically.\n\n"
    "<b>Data sources</b>\n"
    '• <a href="https://www.themoviedb.org/">TMDB</a> — primary (free API key)\n'
    '• <a href="https://www.justwatch.com/">JustWatch</a> — fallback (no key needed)\n\n'
    "<b>Features</b>\n"
    "✅ Auto-notifications on configurable schedule\n"
    "✅ Movie posters included\n"
    "✅ TMDB ratings &amp; genres\n"
    "✅ Direct watch links\n"
    "✅ Multi-region support\n"
    "✅ MongoDB-backed — no data loss on restarts\n"
    "✅ Channel broadcast mode\n\n"
    'Built with <a href="https://pyrogram.org/">Pyrogram</a> 🐍'
)


@Client.on_message(filters.command("about"))
async def about_cmd(client: Client, message: Message):
    await message.reply_text(ABOUT, parse_mode=enums.ParseMode.HTML,
                             disable_web_page_preview=True)


@Client.on_callback_query(filters.regex("^about$"))
async def about_cb(client: Client, cb: CallbackQuery):
    await cb.answer()
    await cb.message.reply_text(ABOUT, parse_mode=enums.ParseMode.HTML,
                                disable_web_page_preview=True)
