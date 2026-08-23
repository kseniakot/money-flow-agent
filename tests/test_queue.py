import asyncio
from collections import defaultdict
from types import SimpleNamespace

from langgraph.types import Command

from app import agent, db
from app.bot import handlers
from app.llm import extract


class FakeBot:
    def __init__(self):
        self._id = 0
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self._id += 1
        self.sent.append(text)
        return SimpleNamespace(message_id=self._id)

    async def delete_message(self, chat_id, mid):
        pass

    async def edit_message_reply_markup(self, chat_id, mid, reply_markup=None):
        pass


class FakeMCP:
    def __init__(self):
        self.saved = []

    async def categories(self):
        return []

    async def save_expenses(self, user_id, items):
        self.saved.append([it["name"] for it in items])
        return {"inserted": len(items), "ids": [1]}


def _item(name):
    return {
        "name": name,
        "category": "прочее",
        "qty": 1,
        "unit": "шт",
        "unit_price": 2.0,
        "price": 2.0,
        "currency": "BYN",
        "purchased_at": "2026-08-23 10:00:00",
        "place": None,
        "source": "text",
    }


async def _approve(app, chat_id):
    graph = app.bot_data["graph"]
    result = await graph.ainvoke(Command(resume={"action": "approve"}), handlers._cfg(chat_id))
    await handlers._present(app, chat_id, result)
    qid = app.chat_data[chat_id].pop("current_queue_id", None)
    if qid is not None:
        await asyncio.to_thread(handlers._q_delete, qid)
    await handlers._pump(app, chat_id)


def test_queue_processes_sequentially(tmp_path, monkeypatch):
    path = str(tmp_path / "q.sqlite")
    monkeypatch.setattr(handlers, "config", SimpleNamespace(db_path=path, default_currency="BYN"))
    conn = db.get_conn(path)
    db.init_db(conn)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")

    names = iter(["первый", "второй", "третий"])
    monkeypatch.setattr(
        extract, "parse", lambda *a, **k: {"items": [_item(next(names))], "meta": {}}
    )

    mcp = FakeMCP()
    graph = agent.build_agent(mcp)
    app = SimpleNamespace(bot=FakeBot(), chat_data=defaultdict(dict), bot_data={"graph": graph, "mcp": mcp})

    for _ in range(3):
        db.enqueue(conn, 100, user["id"], "text", "x", None)

    async def run():
        await handlers._pump(app, 100)          # item 1 -> review
        await _approve(app, 100)                # save 1, pump -> item 2
        await _approve(app, 100)                # save 2, pump -> item 3
        await _approve(app, 100)                # save 3, queue empty

    asyncio.run(run())

    assert mcp.saved == [["первый"], ["второй"], ["третий"]]
    assert db.queue_count(conn, 100) == 0
