from __future__ import annotations

import asyncio
import base64
import tempfile
from datetime import datetime

from langgraph.types import Command
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app import db, transcribe
from app.agent import build_agent
from app.config import config
from app.mcp_client import MCPClient
from app.render import build_preview

KB = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("✅ записать", callback_data="approve"),
            InlineKeyboardButton("❌ отмена", callback_data="cancel"),
        ]
    ]
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _cfg(chat_id: int) -> dict:
    return {"configurable": {"thread_id": str(chat_id)}}


def _register(update: Update) -> dict:
    conn = db.get_conn(config.db_path)
    try:
        u = update.effective_user
        return db.upsert_user(conn, u.id, u.username)
    finally:
        conn.close()


def _initial(user: dict, source: str, text: str, image: str | None, cats: list[str]) -> dict:
    return {
        "user_id": user["id"],
        "source": source,
        "text": text,
        "image": image,
        "categories": cats,
        "default_currency": user["default_currency"],
        "now": _now(),
        "today": _today(),
    }


async def _pending(graph, cfg: dict) -> bool:
    state = await graph.aget_state(cfg)
    return bool(state.next)


async def _present(chat_id: int, context: ContextTypes.DEFAULT_TYPE, result: dict) -> None:
    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        text = build_preview(payload["items"], payload.get("meta", {}))
        await context.bot.send_message(chat_id, text, reply_markup=KB)
    elif result.get("status") == "saved":
        n = result["result"]["inserted"]
        await context.bot.send_message(chat_id, f"✅ Записал {n} поз.")
    elif result.get("status") == "cancelled":
        await context.bot.send_message(chat_id, "Отменено.")


async def _new_expense(update, context, source: str, text: str, image: str | None) -> None:
    graph = context.application.bot_data["graph"]
    mcp = context.application.bot_data["mcp"]
    user = await asyncio.to_thread(_register, update)
    cats = await mcp.categories()
    state = _initial(user, source, text, image, cats)
    result = await graph.ainvoke(state, _cfg(update.effective_chat.id))
    await _present(update.effective_chat.id, context, result)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await asyncio.to_thread(_register, update)
    await update.message.reply_text(
        "Привет! Кидай расходы текстом, голосом или фото чека/выписки.\n"
        "Я распарсю, покажу на проверку, и запишу после твоего ✅."
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    graph = context.application.bot_data["graph"]
    cfg = _cfg(update.effective_chat.id)
    text = update.message.text
    if await _pending(graph, cfg):
        result = await graph.ainvoke(
            Command(resume={"action": "revise", "correction": text}), cfg
        )
        await _present(update.effective_chat.id, context, result)
    else:
        await _new_expense(update, context, "text", text, None)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_file = await update.message.voice.get_file()
    path = tempfile.mktemp(suffix=".ogg")
    await tg_file.download_to_drive(path)
    text = await asyncio.to_thread(transcribe.transcribe, path)
    graph = context.application.bot_data["graph"]
    cfg = _cfg(update.effective_chat.id)
    await update.message.reply_text(f"🎤 {text}")
    if await _pending(graph, cfg):
        result = await graph.ainvoke(
            Command(resume={"action": "revise", "correction": text}), cfg
        )
        await _present(update.effective_chat.id, context, result)
    else:
        await _new_expense(update, context, "voice", text, None)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    graph = context.application.bot_data["graph"]
    cfg = _cfg(update.effective_chat.id)
    if await _pending(graph, cfg):
        await update.message.reply_text(
            "Заверши текущий расход (✅/❌) или поправь текстом — фото-правка пока не поддержана."
        )
        return
    tg_file = await update.message.photo[-1].get_file()
    raw = await tg_file.download_as_bytearray()
    uri = "data:image/jpeg;base64," + base64.b64encode(bytes(raw)).decode()
    caption = update.message.caption or ""
    await _new_expense(update, context, "photo", caption, uri)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    graph = context.application.bot_data["graph"]
    cfg = _cfg(update.effective_chat.id)
    await q.edit_message_reply_markup(None)
    result = await graph.ainvoke(Command(resume={"action": q.data}), cfg)
    await _present(update.effective_chat.id, context, result)


async def _post_init(app: Application) -> None:
    conn = db.get_conn(config.db_path)
    db.init_db(conn)
    conn.close()
    mcp = MCPClient()
    await mcp.start()
    app.bot_data["mcp"] = mcp
    app.bot_data["graph"] = build_agent(mcp)


async def _post_shutdown(app: Application) -> None:
    mcp = app.bot_data.get("mcp")
    if mcp is not None:
        await mcp.stop()


def main() -> None:
    app = (
        Application.builder()
        .token(config.tg_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
