import asyncio
import base64
import csv
import io
import logging
import shlex
import tempfile
from contextlib import AsyncExitStack
from datetime import datetime, timedelta

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

from app import backup, db, rates
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


async def _pending(graph, cfg: dict) -> bool:
    state = await graph.aget_state(cfg)
    return bool(state.next)


def _cd(app, chat_id: int) -> dict:
    return app.chat_data[chat_id]


async def _clear_kb(app, chat_id: int) -> None:
    cd = _cd(app, chat_id)
    for mid in cd.pop("kb_msgs", []):
        try:
            await app.bot.edit_message_reply_markup(chat_id, mid, reply_markup=None)
        except Exception:
            pass


async def _send_kb(app, chat_id: int, text: str) -> None:
    await _clear_kb(app, chat_id)
    msg = await app.bot.send_message(chat_id, text, reply_markup=KB)
    _cd(app, chat_id).setdefault("kb_msgs", []).append(msg.message_id)


async def _present(app, chat_id: int, result: dict) -> None:
    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        text = build_preview(payload["items"], payload.get("meta", {}))
        await _send_kb(app, chat_id, text + "\n\n" + REVIEW_HINT)
    elif result.get("status") == "saved":
        await _clear_kb(app, chat_id)
        n = result["result"]["inserted"]
        await app.bot.send_message(chat_id, f"✅ Записал {n} поз.")
    elif result.get("status") == "cancelled":
        await _clear_kb(app, chat_id)
        await app.bot.send_message(chat_id, "🗑 Удалено.")


async def _processing(app, chat_id: int, coro):
    pid = None
    try:
        pid = (await app.bot.send_message(chat_id, "⏳ Обрабатываю…")).message_id
    except Exception:
        pass
    result = await coro
    if pid is not None:
        try:
            await app.bot.delete_message(chat_id, pid)
        except Exception:
            pass
    return result


def _user_currency(user_id: int) -> str:
    conn = db.get_conn(config.db_path)
    try:
        u = db.get_user(conn, user_id)
        return u["default_currency"] if u else config.default_currency
    finally:
        conn.close()


def _q_enqueue(chat_id, user_id, source, text, file_id) -> int:
    conn = db.get_conn(config.db_path)
    try:
        return db.enqueue(conn, chat_id, user_id, source, text, file_id)
    finally:
        conn.close()


def _q_front(chat_id):
    conn = db.get_conn(config.db_path)
    try:
        return db.queue_front(conn, chat_id)
    finally:
        conn.close()


def _q_delete(item_id):
    conn = db.get_conn(config.db_path)
    try:
        db.queue_delete(conn, item_id)
    finally:
        conn.close()


def _q_count(chat_id):
    conn = db.get_conn(config.db_path)
    try:
        return db.queue_count(conn, chat_id)
    finally:
        conn.close()


async def _transcribe_file(bot, file_id: str) -> str:
    tg_file = await bot.get_file(file_id)
    path = tempfile.mktemp(suffix=".ogg")
    await tg_file.download_to_drive(path)
    return await asyncio.to_thread(transcribe.transcribe, path)


async def _resolve_input(app, front: dict) -> tuple[str, str | None]:
    source = front["source"]
    if source == "voice":
        text = await _transcribe_file(app.bot, front["file_id"])
        await app.bot.send_message(front["chat_id"], f"🎤 {text}")
        return text, None
    if source == "photo":
        tg_file = await app.bot.get_file(front["file_id"])
        raw = await tg_file.download_as_bytearray()
        uri = "data:image/jpeg;base64," + base64.b64encode(bytes(raw)).decode()
        return front["text"] or "", uri
    return front["text"] or "", None


async def _pump(app, chat_id: int) -> None:
    cd = _cd(app, chat_id)
    if cd.get("busy"):
        return
    cd["busy"] = True  # claim atomically (no await between check and set)
    try:
        graph = app.bot_data["graph"]
        cfg = _cfg(chat_id)
        if await _pending(graph, cfg):
            return
        front = await asyncio.to_thread(_q_front, chat_id)
        if front is None:
            return
        cd["current_queue_id"] = front["id"]
        remaining = await asyncio.to_thread(_q_count, chat_id)
        pid = None
        try:
            pid = (await app.bot.send_message(chat_id, f"⏳ Обрабатываю… (в очереди: {remaining})")).message_id
        except Exception:
            pass
        text, image = await _resolve_input(app, front)
        cats = await app.bot_data["mcp"].categories()
        currency = await asyncio.to_thread(_user_currency, front["user_id"])
        state = {
            "user_id": front["user_id"],
            "source": front["source"],
            "text": text,
            "image": image,
            "categories": cats,
            "default_currency": currency,
            "now": _now(),
            "today": _today(),
        }
        log.info("pump chat %s: item %s source=%s", chat_id, front["id"], front["source"])
        result = await graph.ainvoke(state, cfg)
        if pid is not None:
            try:
                await app.bot.delete_message(chat_id, pid)
            except Exception:
                pass
        await _present(app, chat_id, result)
    finally:
        cd["busy"] = False


async def _handle_input(update, context, source: str, text: str | None, file_id: str | None) -> None:
    app = context.application
    chat_id = update.effective_chat.id
    user = await asyncio.to_thread(_register, update)
    graph = app.bot_data["graph"]
    cfg = _cfg(chat_id)
    cd = _cd(app, chat_id)

    if await _pending(graph, cfg):
        # a review is being shown -> this message is a correction to it
        if source == "photo":
            await update.message.reply_text(
                "Фото-правка не поддержана. Заверши текущий расход (записать/удалить)."
            )
            return
        if cd.get("busy"):
            # busy processing a previous correction -> ignore this one
            return
        cd["busy"] = True
        try:
            if source == "voice":
                text = await _transcribe_file(app.bot, file_id)
                await update.message.reply_text(f"🎤 {text}")
            await _clear_kb(app, chat_id)
            result = await _processing(
                app,
                chat_id,
                graph.ainvoke(Command(resume={"action": "revise", "correction": text}), cfg),
            )
            await _present(app, chat_id, result)
        finally:
            cd["busy"] = False
        return

    # no active review -> queue this input instantly (raw), then process
    await asyncio.to_thread(_q_enqueue, chat_id, user["id"], source, text, file_id)
    n = await asyncio.to_thread(_q_count, chat_id)
    await update.message.reply_text(f"⏳ Принято. В очереди: {n}.")
    await _pump(app, chat_id)


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


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    log.info("text from chat %s: %r", update.effective_chat.id, text)
    await _handle_input(update, context, "text", text, None)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.info("voice from chat %s", update.effective_chat.id)
    await _handle_input(update, context, "voice", None, update.message.voice.file_id)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caption = update.message.caption or ""
    log.info("photo from chat %s, caption=%r", update.effective_chat.id, caption)
    await _handle_input(update, context, "photo", caption, update.message.photo[-1].file_id)


def _delete_expense(expense_id: int) -> None:
    conn = db.get_conn(config.db_path)
    try:
        db.delete_expense(conn, expense_id)
    finally:
        conn.close()


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = context.application
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    chat_id = update.effective_chat.id
    cd = _cd(app, chat_id)
    log.info("button %r from chat %s", q.data, chat_id)

    if q.data.startswith("undo:"):
        try:
            await q.edit_message_reply_markup(None)
        except Exception:
            pass
        await asyncio.to_thread(_delete_expense, int(q.data.split(":")[1]))
        await app.bot.send_message(chat_id, "↩️ Списание отменено.")
        return

    if cd.get("busy"):
        await app.bot.send_message(chat_id, "⏳ Секунду, обрабатываю…")
        return

    graph = app.bot_data["graph"]
    cfg = _cfg(chat_id)
    if not await _pending(graph, cfg):
        await app.bot.send_message(chat_id, "Эта проверка уже завершена.")
        return
    try:
        await q.edit_message_reply_markup(None)
    except Exception:
        pass

    cd["busy"] = True
    try:
        result = await graph.ainvoke(Command(resume={"action": q.data}), cfg)
        await _present(app, chat_id, result)
    finally:
        cd["busy"] = False

    if result.get("status") in ("saved", "cancelled"):
        qid = cd.pop("current_queue_id", None)
        if qid is not None:
            await asyncio.to_thread(_q_delete, qid)
        replace_id = cd.pop("replace_id", None)
        if replace_id is not None:
            await asyncio.to_thread(_delete_expense, replace_id)
            log.info("edit: removed original expense %s", replace_id)
        await _pump(app, chat_id)


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
    if not rows:
        await update.message.reply_text(f"За {start} — {end} расходов нет.")
        return
    chat_id = update.effective_chat.id
    data = io.BytesIO(await asyncio.to_thread(reports.build_report_xlsx, rows))
    await context.bot.send_document(
        chat_id,
        InputFile(data, filename=f"report_{start}_{end}.xlsx"),
        caption="Разверни категорию (значок + слева), чтобы увидеть покупки.",
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
        failed = False
        rendered = []
        for w in ws:
            try:
                usd = rates.to_usd(w["balance"], w["currency"])
                total += usd
            except Exception:
                usd = None
                failed = True
            rendered.append((w, usd))
        return rendered, total, failed

    rendered, total, failed = await asyncio.to_thread(work)
    if not rendered:
        await update.message.reply_text("Кошельков пока нет.")
        return
    lines = ["💰 Кошельки:"]
    for w, usd in rendered:
        tag = "🐷" if w["kind"] == "savings" else "💳"
        usd_str = f"≈ {usd:.2f}$" if usd is not None else "≈ ?$"
        lines.append(f"{tag} {w['currency']} ({w['kind']}): {w['balance']:.2f} {usd_str}")
    suffix = " (без недоступных)" if failed else ""
    lines.append(f"─────\nВсего ≈ {total:.2f}${suffix}")
    if failed:
        lines.append("⚠️ Курс НБ РБ недоступен для части валют — итог в USD неполный.")
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
        today = datetime.now().strftime("%Y-%m-%d")
        start_date = today
        if rest:
            try:
                datetime.strptime(rest[0], "%Y-%m-%d")
                start_date = rest[0]
                rest = rest[1:]
            except ValueError:
                pass
        if start_date < today:
            await update.message.reply_text(
                f"⚠️ Дата старта не должна быть раньше сегодня ({today}). "
                "Прошлые месяцы не начисляются задним числом."
            )
            return
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
    app = context.application
    chat_id = update.effective_chat.id
    graph = app.bot_data["graph"]
    cfg = _cfg(chat_id)
    cd = _cd(app, chat_id)
    if cd.get("busy") or await _pending(graph, cfg):
        await update.message.reply_text(
            "⏳ Заверши текущий расход (записать/удалить), потом /edit."
        )
        return
    if await asyncio.to_thread(_q_front, chat_id) is not None:
        await update.message.reply_text("⏳ Сначала разгреби очередь расходов, потом /edit.")
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
        "discount": row["discount"],
        "price": row["price"],
        "currency": row["currency"],
        "purchased_at": row["purchased_at"],
        "place": row["place"],
        "source": row["source"],
    }
    cd["replace_id"] = eid
    cats = await app.bot_data["mcp"].categories()
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
    cd["busy"] = True
    try:
        result = await graph.ainvoke(state, cfg)
        await _present(app, chat_id, result)
    finally:
        cd["busy"] = False


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


async def _backup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    age = await asyncio.to_thread(backup.newest_backup_age_hours, config.backup_dir)
    if age is None or age >= 20:
        await asyncio.to_thread(
            backup.backup_db, config.db_path, config.backup_dir, config.backup_keep
        )


async def _post_init(app: Application) -> None:
    conn = db.get_conn(config.db_path)
    db.init_db(conn)
    conn.close()
    await asyncio.to_thread(
        backup.backup_db, config.db_path, config.backup_dir, config.backup_keep
    )
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
    app.job_queue.run_repeating(
        _subscription_job, interval=timedelta(hours=6), first=timedelta(hours=6)
    )
    app.job_queue.run_repeating(
        _backup_job, interval=timedelta(hours=6), first=timedelta(hours=6)
    )
    charged = await asyncio.to_thread(_charge_due, datetime.now())
    await _notify_charged(app.bot, charged)
    await _resume_queues(app)


async def _resume_queues(app: Application) -> None:
    conn = db.get_conn(config.db_path)
    try:
        chats = db.queue_chats(conn)
    finally:
        conn.close()
    graph = app.bot_data["graph"]
    for chat_id in chats:
        cfg = _cfg(chat_id)
        if await _pending(graph, cfg):
            snap = await graph.aget_state(cfg)
            items = snap.values.get("items", [])
            meta = snap.values.get("meta", {})
            front = await asyncio.to_thread(_q_front, chat_id)
            if front is not None:
                _cd(app, chat_id)["current_queue_id"] = front["id"]
            if items:
                await _send_kb(app, chat_id, build_preview(items, meta) + "\n\n" + REVIEW_HINT)
        else:
            await _pump(app, chat_id)


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
