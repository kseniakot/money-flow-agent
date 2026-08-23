import asyncio
import base64
import csv
import io
import logging
import shlex
import tempfile
from contextlib import AsyncExitStack
from datetime import datetime
from datetime import time as dtime

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
)
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from app import db, rates
from app.agent import build_agent
from app.bot import reports, transcribe
from app.bot.render import build_preview
from app.config import config
from app.logging_setup import setup_logging
from app.mcp.client import MCPClient

log = logging.getLogger(__name__)

KB = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("✅ записать", callback_data="approve"),
            InlineKeyboardButton("🗑 удалить", callback_data="cancel"),
        ]
    ]
)

REVIEW_HINT = "✏️ Правка — просто пришли следующим сообщением (текст/голос), если не жмёшь «записать»/«удалить»."

COMMANDS = [
    BotCommand("start", "как пользоваться ботом"),
    BotCommand("report", "отчёт за период: /report 2026-08-01 2026-08-31"),
    BotCommand("wallets", "балансы кошельков и итог в USD"),
    BotCommand("deposit", "пополнить кошелёк: /deposit 100 USD"),
    BotCommand("savings", "копилка: /savings 100 USD (без аргументов — показать)"),
    BotCommand("correct", "выставить баланс: /correct USD 90 [savings]"),
    BotCommand("subs", "подписки: /subs, add, del"),
    BotCommand("categories", "список категорий"),
    BotCommand("currency", "валюта по умолчанию: /currency USD"),
    BotCommand("history", "вся история покупок (CSV-файл)"),
    BotCommand("edit", "поправить покупку: /edit <id>"),
    BotCommand("del", "удалить покупку: /del <id>"),
    BotCommand("undo", "удалить последний расход"),
    BotCommand("export", "выгрузить расходы в CSV"),
]


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
        return db.upsert_user(conn, u.id, u.username, config.default_currency)
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


def _is_busy(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.chat_data.get("busy", False)


async def _clear_kb(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    for mid in context.chat_data.pop("kb_msgs", []):
        try:
            await context.bot.edit_message_reply_markup(chat_id, mid, reply_markup=None)
        except Exception:
            pass


async def _send_kb(chat_id: int, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    await _clear_kb(chat_id, context)
    msg = await context.bot.send_message(chat_id, text, reply_markup=KB)
    context.chat_data.setdefault("kb_msgs", []).append(msg.message_id)


async def _present(chat_id: int, context: ContextTypes.DEFAULT_TYPE, result: dict) -> None:
    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        text = build_preview(payload["items"], payload.get("meta", {}))
        await _send_kb(chat_id, context, text + "\n\n" + REVIEW_HINT)
    elif result.get("status") == "saved":
        await _clear_kb(chat_id, context)
        n = result["result"]["inserted"]
        await context.bot.send_message(chat_id, f"✅ Записал {n} поз.")
    elif result.get("status") == "cancelled":
        await _clear_kb(chat_id, context)
        await context.bot.send_message(chat_id, "🗑 Удалено.")


async def _remind_pending(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_kb(chat_id, context, "Сначала реши, что делать с текущим расходом:")


async def _send_processing(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = await context.bot.send_message(chat_id, "⏳ Обрабатываю…")
    return msg.message_id


async def _delete_msg(chat_id: int, context: ContextTypes.DEFAULT_TYPE, message_id: int) -> None:
    try:
        await context.bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def _new_expense(update, context, source: str, text: str, image: str | None) -> None:
    context.chat_data.pop("replace_id", None)
    chat_id = update.effective_chat.id
    graph = context.application.bot_data["graph"]
    mcp = context.application.bot_data["mcp"]
    user = await asyncio.to_thread(_register, update)
    cats = await mcp.categories()
    state = _initial(user, source, text, image, cats)
    pid = await _send_processing(chat_id, context)
    result = await graph.ainvoke(state, _cfg(chat_id))
    await _delete_msg(chat_id, context, pid)
    await _present(chat_id, context, result)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await asyncio.to_thread(_register, update)
    await update.message.reply_text(
        "Привет! Кидай расходы текстом, голосом или фото чека/выписки.\n"
        "Я распарсю, покажу на проверку, и запишу после твоего ✅.\n\n"
        "Команды (меню слева от поля ввода):\n"
        "/report — отчёт за период\n"
        "/wallets — балансы кошельков\n"
        "/deposit — пополнить кошелёк\n"
        "/savings — копилка\n"
        "/correct — поправить баланс\n"
        "/subs — подписки\n"
        "/categories — категории\n"
        "/currency — валюта по умолчанию\n"
        "/undo — удалить последний расход\n"
        "/export — выгрузить CSV"
    )


async def _apply_correction(update, context, graph, cfg, text: str) -> None:
    chat_id = update.effective_chat.id
    await _clear_kb(chat_id, context)
    pid = await _send_processing(chat_id, context)
    result = await graph.ainvoke(
        Command(resume={"action": "revise", "correction": text}), cfg
    )
    await _delete_msg(chat_id, context, pid)
    await _present(chat_id, context, result)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _is_busy(context):
        await update.message.reply_text("⏳ Секунду, обрабатываю предыдущее…")
        return
    context.chat_data["busy"] = True
    try:
        graph = context.application.bot_data["graph"]
        cfg = _cfg(update.effective_chat.id)
        text = update.message.text
        log.info("text from chat %s: %r", update.effective_chat.id, text)
        if await _pending(graph, cfg):
            await _apply_correction(update, context, graph, cfg, text)
        else:
            await _new_expense(update, context, "text", text, None)
    finally:
        context.chat_data["busy"] = False


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _is_busy(context):
        await update.message.reply_text("⏳ Секунду, обрабатываю предыдущее…")
        return
    context.chat_data["busy"] = True
    try:
        log.info("voice from chat %s", update.effective_chat.id)
        tg_file = await update.message.voice.get_file()
        path = tempfile.mktemp(suffix=".ogg")
        await tg_file.download_to_drive(path)
        text = await asyncio.to_thread(transcribe.transcribe, path)
        log.info("transcribed: %r", text)
        graph = context.application.bot_data["graph"]
        cfg = _cfg(update.effective_chat.id)
        await update.message.reply_text(f"🎤 {text}")
        if await _pending(graph, cfg):
            await _apply_correction(update, context, graph, cfg, text)
        else:
            await _new_expense(update, context, "voice", text, None)
    finally:
        context.chat_data["busy"] = False


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _is_busy(context):
        await update.message.reply_text("⏳ Секунду, обрабатываю предыдущее…")
        return
    context.chat_data["busy"] = True
    try:
        graph = context.application.bot_data["graph"]
        cfg = _cfg(update.effective_chat.id)
        if await _pending(graph, cfg):
            await _remind_pending(update.effective_chat.id, context)
            return
        tg_file = await update.message.photo[-1].get_file()
        raw = await tg_file.download_as_bytearray()
        uri = "data:image/jpeg;base64," + base64.b64encode(bytes(raw)).decode()
        caption = update.message.caption or ""
        log.info("photo from chat %s, caption=%r", update.effective_chat.id, caption)
        await _new_expense(update, context, "photo", caption, uri)
    finally:
        context.chat_data["busy"] = False


def _delete_expense(expense_id: int) -> None:
    conn = db.get_conn(config.db_path)
    try:
        db.delete_expense(conn, expense_id)
    finally:
        conn.close()


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    chat_id = update.effective_chat.id
    log.info("button %r from chat %s", q.data, chat_id)

    if q.data.startswith("undo:"):
        await q.edit_message_reply_markup(None)
        await asyncio.to_thread(_delete_expense, int(q.data.split(":")[1]))
        await context.bot.send_message(chat_id, "↩️ Списание отменено.")
        return

    if _is_busy(context):
        await context.bot.send_message(chat_id, "⏳ Секунду, обрабатываю…")
        return

    await q.edit_message_reply_markup(None)
    graph = context.application.bot_data["graph"]
    cfg = _cfg(chat_id)
    if not await _pending(graph, cfg):
        await context.bot.send_message(chat_id, "Эта проверка уже завершена.")
        return

    context.chat_data["busy"] = True
    try:
        result = await graph.ainvoke(Command(resume={"action": q.data}), cfg)
        await _present(chat_id, context, result)
        replace_id = context.chat_data.pop("replace_id", None)
        if replace_id is not None and result.get("status") in ("saved", "cancelled"):
            await asyncio.to_thread(_delete_expense, replace_id)
            log.info("edit: removed original expense %s", replace_id)
    finally:
        context.chat_data["busy"] = False


def _charge_due(now: datetime, db_path: str | None = None, only_sub_id: int | None = None) -> list[dict]:
    conn = db.get_conn(db_path or config.db_path)
    try:
        charged = []
        for sub in db.due_subscriptions(conn, now):
            if only_sub_id is not None and sub["id"] != only_sub_id:
                continue
            res = db.charge_subscription(conn, sub, now.strftime("%Y-%m-%d %H:%M:%S"))
            user = db.get_user(conn, sub["user_id"])
            charged.append({"sub": sub, "expense_id": res["expense_id"], "tg": user["tg_user_id"]})
        return charged
    finally:
        conn.close()


async def _notify_charged(bot, charged: list[dict]) -> None:
    for c in charged:
        sub = c["sub"]
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("↩️ отменить", callback_data=f"undo:{c['expense_id']}")]]
        )
        await bot.send_message(
            c["tg"],
            f"🔁 Подписка «{sub['name']}»: −{sub['amount']} {sub['currency']}",
            reply_markup=kb,
        )


async def _subscription_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    charged = await asyncio.to_thread(_charge_due, datetime.now())
    await _notify_charged(context.bot, charged)


def _float(s: str) -> float:
    return float(s.replace(",", "."))


async def categories_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cats = await context.application.bot_data["mcp"].categories()
    body = "\n".join(f"• {c}" for c in cats) if cats else "пока нет"
    await update.message.reply_text("Категории:\n" + body)


async def currency_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await asyncio.to_thread(_register, update)
    if not context.args:
        await update.message.reply_text(
            f"Валюта по умолчанию: {user['default_currency']}\nСменить: /currency USD"
        )
        return
    currency = context.args[0].upper()

    def work():
        conn = db.get_conn(config.db_path)
        try:
            db.set_default_currency(conn, user["id"], currency)
        finally:
            conn.close()

    await asyncio.to_thread(work)
    await update.message.reply_text(f"✅ Валюта по умолчанию теперь {currency}.")


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text("Формат: /report 2026-08-01 2026-08-31")
        return
    start, end = context.args
    user = await asyncio.to_thread(_register, update)

    def work():
        conn = db.get_conn(config.db_path)
        try:
            return db.query_expenses(conn, start, end, user["id"])
        finally:
            conn.close()

    rows = await asyncio.to_thread(work)
    await update.message.reply_text(reports.build_report_text(rows, start, end))
    if not rows:
        return
    chat_id = update.effective_chat.id
    by_cat = sorted(rows, key=lambda r: (r["category_name"], r["purchased_at"]))
    data = io.BytesIO(reports.expenses_csv(by_cat))
    await context.bot.send_document(
        chat_id, InputFile(data, filename=f"report_{start}_{end}.csv")
    )
    for cur, png in await asyncio.to_thread(reports.build_charts, rows):
        await context.bot.send_photo(chat_id, png)


async def wallets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await asyncio.to_thread(_register, update)

    def work():
        conn = db.get_conn(config.db_path)
        try:
            ws = db.list_wallets(conn, user["id"])
        finally:
            conn.close()
        total = 0.0
        rendered = []
        for w in ws:
            usd = rates.to_usd(w["balance"], w["currency"])
            total += usd
            rendered.append((w, usd))
        return rendered, total

    rendered, total = await asyncio.to_thread(work)
    if not rendered:
        await update.message.reply_text("Кошельков пока нет.")
        return
    lines = ["💰 Кошельки:"]
    for w, usd in rendered:
        tag = "🐷" if w["kind"] == "savings" else "💳"
        lines.append(f"{tag} {w['currency']} ({w['kind']}): {w['balance']:.2f} ≈ {usd:.2f}$")
    lines.append(f"─────\nВсего ≈ {total:.2f}$")
    await update.message.reply_text("\n".join(lines))


async def deposit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /deposit 100 USD [комментарий]")
        return
    try:
        amount = _float(context.args[0])
    except ValueError:
        await update.message.reply_text("Сумма числом: /deposit 100 USD")
        return
    currency = context.args[1].upper()
    comment = " ".join(context.args[2:]) or None
    user = await asyncio.to_thread(_register, update)

    def work():
        conn = db.get_conn(config.db_path)
        try:
            w = db.get_or_create_wallet(conn, user["id"], currency, "spending")
            db.add_movement(conn, w["id"], "deposit", amount, comment)
            return db.wallet_balance(conn, w["id"])
        finally:
            conn.close()

    bal = await asyncio.to_thread(work)
    await update.message.reply_text(f"✅ +{amount:.2f} {currency}. Баланс: {bal:.2f} {currency}")


async def savings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await asyncio.to_thread(_register, update)
    args = context.args
    if not args:
        def show():
            conn = db.get_conn(config.db_path)
            try:
                return [w for w in db.list_wallets(conn, user["id"]) if w["kind"] == "savings"]
            finally:
                conn.close()

        ws = await asyncio.to_thread(show)
        if not ws:
            await update.message.reply_text("Копилка пуста. Пополнить: /savings 100 USD")
            return
        body = "\n".join(f"{w['currency']}: {w['balance']:.2f}" for w in ws)
        await update.message.reply_text("🐷 Копилка:\n" + body)
        return

    if len(args) < 2:
        await update.message.reply_text("Формат: /savings 100 USD [комментарий]")
        return
    try:
        amount = _float(args[0])
    except ValueError:
        await update.message.reply_text("Сумма числом: /savings 100 USD")
        return
    currency = args[1].upper()
    comment = " ".join(args[2:]) or None

    def work():
        conn = db.get_conn(config.db_path)
        try:
            w = db.get_or_create_wallet(conn, user["id"], currency, "savings")
            db.add_movement(conn, w["id"], "deposit", amount, comment)
            return db.wallet_balance(conn, w["id"])
        finally:
            conn.close()

    bal = await asyncio.to_thread(work)
    await update.message.reply_text(f"🐷 +{amount:.2f} {currency}. Копилка: {bal:.2f} {currency}")


async def correct_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Формат: /correct USD 90 [savings]")
        return
    currency = args[0].upper()
    try:
        target = _float(args[1])
    except ValueError:
        await update.message.reply_text("Цель числом: /correct USD 90")
        return
    kind = "savings" if len(args) > 2 and args[2].lower() == "savings" else "spending"
    user = await asyncio.to_thread(_register, update)

    def work():
        conn = db.get_conn(config.db_path)
        try:
            w = db.get_or_create_wallet(conn, user["id"], currency, kind)
            cur = db.wallet_balance(conn, w["id"])
            db.add_movement(conn, w["id"], "correction", round(target - cur, 2), "correction")
            return db.wallet_balance(conn, w["id"])
        finally:
            conn.close()

    bal = await asyncio.to_thread(work)
    await update.message.reply_text(f"🛠 Баланс {currency} ({kind}) = {bal:.2f}")


async def subs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await asyncio.to_thread(_register, update)
    try:
        args = shlex.split(update.message.text or "")[1:]
    except ValueError:
        args = context.args

    if not args:
        def show():
            conn = db.get_conn(config.db_path)
            try:
                return db.list_subscriptions(conn, user["id"])
            finally:
                conn.close()

        subs = await asyncio.to_thread(show)
        if not subs:
            await update.message.reply_text(
                'Подписок нет. Добавить: /subs add "Claude Code" 50 USD [start_date] [коммент]\n'
                "start_date по умолчанию сегодня; имя в кавычках, если есть пробел."
            )
            return
        lines = ["🔁 Подписки:"]
        for s in subs:
            c = f" · {s['comment']}" if s.get("comment") else ""
            lines.append(
                f"#{s['id']} {s['name']} — {s['amount']:.2f} {s['currency']},"
                f" {s['day_of_month']} числа (с {s['start_date']}){c}"
            )
        lines.append("\nУдалить: /subs del <id>")
        await update.message.reply_text("\n".join(lines))
        return

    if args[0] == "del" and len(args) == 2:
        try:
            sid = int(args[1])
        except ValueError:
            await update.message.reply_text("id числом: /subs del 3")
            return

        def work():
            conn = db.get_conn(config.db_path)
            try:
                db.deactivate_subscription(conn, sid)
            finally:
                conn.close()

        await asyncio.to_thread(work)
        await update.message.reply_text(f"Подписка #{sid} удалена.")
        return

    if args[0] == "add" and len(args) >= 4:
        try:
            amount = _float(args[2])
        except ValueError:
            await update.message.reply_text(
                'Формат: /subs add "<name>" <amount> <currency> [start_date] [коммент]'
            )
            return
        name = args[1]
        currency = args[3].upper()
        rest = args[4:]
        start_date = datetime.now().strftime("%Y-%m-%d")
        if rest:
            try:
                datetime.strptime(rest[0], "%Y-%m-%d")
                start_date = rest[0]
                rest = rest[1:]
            except ValueError:
                pass
        comment = " ".join(rest) or None

        def work():
            conn = db.get_conn(config.db_path)
            try:
                return db.create_subscription(conn, user["id"], name, amount, currency, start_date, comment)
            finally:
                conn.close()

        s = await asyncio.to_thread(work)
        charged = await asyncio.to_thread(_charge_due, datetime.now(), None, s["id"])
        msg = (
            f"✅ Подписка #{s['id']} {name}: {amount:.2f} {currency},"
            f" {s['day_of_month']} числа (с {start_date})"
        )
        if charged:
            msg += f"\n🔁 Списал первый платёж: −{amount:.2f} {currency}"
        await update.message.reply_text(msg)
        return

    await update.message.reply_text(
        'Формат: /subs | /subs add "<name>" <amount> <currency> [start_date] [коммент] | /subs del <id>'
    )


async def undo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await asyncio.to_thread(_register, update)

    def work():
        conn = db.get_conn(config.db_path)
        try:
            last = db.last_expense(conn, user["id"])
            if last:
                db.delete_expense(conn, last["id"])
            return last
        finally:
            conn.close()

    last = await asyncio.to_thread(work)
    if not last:
        await update.message.reply_text("Нечего отменять.")
        return
    await update.message.reply_text(
        f"↩️ Удалил: {last['product_name']} — {last['price']:.2f} {last['currency']}"
    )


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await asyncio.to_thread(_register, update)

    def work():
        conn = db.get_conn(config.db_path)
        try:
            rows = db.query_expenses(conn, "0001-01-01", "9999-12-31", user["id"])
        finally:
            conn.close()
        rows.sort(key=lambda r: r["id"], reverse=True)
        return rows

    rows = await asyncio.to_thread(work)
    if not rows:
        await update.message.reply_text("Расходов пока нет.")
        return
    data = io.BytesIO(reports.expenses_csv(rows))
    await context.bot.send_document(
        update.effective_chat.id,
        InputFile(data, filename="history.csv"),
        caption=f"Вся история: {len(rows)} записей. Поправить: /edit <id> · Удалить: /del <id>",
    )


async def del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Формат: /del <id> (id смотри в /history)")
        return
    try:
        eid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("id числом: /del 42")
        return
    user = await asyncio.to_thread(_register, update)

    def work():
        conn = db.get_conn(config.db_path)
        try:
            row = db.get_expense(conn, eid, user["id"])
            if row:
                db.delete_expense(conn, eid)
            return row
        finally:
            conn.close()

    row = await asyncio.to_thread(work)
    if not row:
        await update.message.reply_text(f"Покупка #{eid} не найдена.")
        return
    await update.message.reply_text(
        f"🗑 Удалил #{eid}: {row['product_name']} — {row['price']:.2f} {row['currency']}"
    )


async def edit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Формат: /edit <id> (id смотри в /history)")
        return
    try:
        eid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("id числом: /edit 42")
        return
    chat_id = update.effective_chat.id
    graph = context.application.bot_data["graph"]
    cfg = _cfg(chat_id)
    if _is_busy(context):
        await update.message.reply_text("⏳ Секунду, обрабатываю…")
        return
    if await _pending(graph, cfg):
        await _remind_pending(chat_id, context)
        return
    user = await asyncio.to_thread(_register, update)

    def work():
        conn = db.get_conn(config.db_path)
        try:
            return db.get_expense(conn, eid, user["id"])
        finally:
            conn.close()

    row = await asyncio.to_thread(work)
    if not row:
        await update.message.reply_text(f"Покупка #{eid} не найдена.")
        return

    item = {
        "name": row["product_name"],
        "category": row["category_name"],
        "qty": row["qty"],
        "unit": row["unit"],
        "unit_price": row["unit_price"],
        "price": row["price"],
        "currency": row["currency"],
        "purchased_at": row["purchased_at"],
        "place": row["place"],
        "source": row["source"],
    }
    context.chat_data["replace_id"] = eid
    cats = await context.application.bot_data["mcp"].categories()
    state = {
        "user_id": user["id"],
        "source": "edit",
        "text": "",
        "image": None,
        "categories": cats,
        "default_currency": user["default_currency"],
        "now": _now(),
        "today": _today(),
        "items": [item],
    }
    log.info("edit: open expense %s for chat %s", eid, chat_id)
    await update.message.reply_text(f"✏️ Правка #{eid}. Пришли изменения следующим сообщением.")
    context.chat_data["busy"] = True
    try:
        result = await graph.ainvoke(state, cfg)
        await _present(chat_id, context, result)
    finally:
        context.chat_data["busy"] = False


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await asyncio.to_thread(_register, update)

    def work():
        conn = db.get_conn(config.db_path)
        try:
            return db.query_expenses(conn, "0001-01-01", "9999-12-31", user["id"])
        finally:
            conn.close()

    rows = await asyncio.to_thread(work)
    if not rows:
        await update.message.reply_text("Расходов нет.")
        return
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["purchased_at", "category", "product", "qty", "unit_price", "price", "currency", "place", "source"]
    )
    for r in rows:
        writer.writerow(
            [r["purchased_at"], r["category_name"], r["product_name"], r["qty"],
             r["unit_price"], r["price"], r["currency"], r["place"] or "", r["source"]]
        )
    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    await context.bot.send_document(
        update.effective_chat.id, InputFile(data, filename="expenses.csv")
    )


async def _post_init(app: Application) -> None:
    conn = db.get_conn(config.db_path)
    db.init_db(conn)
    conn.close()
    mcp = MCPClient()
    await mcp.start()
    stack = AsyncExitStack()
    saver = await stack.enter_async_context(
        AsyncSqliteSaver.from_conn_string(str(config.checkpoint_path))
    )
    await saver.setup()
    app.bot_data["mcp"] = mcp
    app.bot_data["stack"] = stack
    app.bot_data["graph"] = build_agent(mcp, saver)
    await app.bot.set_my_commands(COMMANDS)
    app.job_queue.run_daily(_subscription_job, time=dtime(hour=9, minute=0))
    charged = await asyncio.to_thread(_charge_due, datetime.now())
    await _notify_charged(app.bot, charged)


async def _post_shutdown(app: Application) -> None:
    mcp = app.bot_data.get("mcp")
    if mcp is not None:
        await mcp.stop()
    stack = app.bot_data.get("stack")
    if stack is not None:
        await stack.aclose()


async def _ignore_edited(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.edited_message is not None:
        raise ApplicationHandlerStop


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("handler error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat is not None:
        try:
            await context.bot.send_message(
                update.effective_chat.id, "⚠️ Что-то пошло не так, попробуй ещё раз."
            )
        except Exception:
            pass


def main() -> None:
    setup_logging()
    log.info("starting bot")
    app = (
        Application.builder()
        .token(config.tg_token)
        .concurrent_updates(True)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(TypeHandler(Update, _ignore_edited), group=-1)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("wallets", wallets_cmd))
    app.add_handler(CommandHandler("deposit", deposit_cmd))
    app.add_handler(CommandHandler("savings", savings_cmd))
    app.add_handler(CommandHandler("correct", correct_cmd))
    app.add_handler(CommandHandler("subs", subs_cmd))
    app.add_handler(CommandHandler("categories", categories_cmd))
    app.add_handler(CommandHandler("currency", currency_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("edit", edit_cmd))
    app.add_handler(CommandHandler("del", del_cmd))
    app.add_handler(CommandHandler("undo", undo_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
