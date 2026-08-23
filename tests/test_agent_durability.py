import asyncio
from contextlib import AsyncExitStack

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app import agent
from app.llm import extract


class FakeMCP:
    def __init__(self):
        self.saved = None

    async def save_expenses(self, user_id, items):
        self.saved = items
        return {"inserted": len(items), "ids": [1]}


def _item():
    return {
        "name": "молоко",
        "category": "молочная продукция",
        "qty": 1,
        "unit_price": 1.92,
        "price": 1.92,
        "currency": "BYN",
        "purchased_at": "2026-08-15 19:40:00",
        "place": None,
        "source": "text",
    }


def _initial():
    return {
        "user_id": 1,
        "source": "text",
        "text": "молоко 1.92",
        "image": None,
        "categories": ["молочная продукция"],
        "default_currency": "BYN",
        "now": "2026-08-15 19:40:00",
        "today": "2026-08-15",
    }


def test_interrupt_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "parse", lambda *a, **k: {"items": [_item()], "meta": {}})
    path = str(tmp_path / "cp.sqlite")
    cfg = {"configurable": {"thread_id": "t1"}}
    mcp2 = FakeMCP()

    async def run():
        async with AsyncExitStack() as s1:
            saver1 = await s1.enter_async_context(AsyncSqliteSaver.from_conn_string(path))
            await saver1.setup()
            graph1 = agent.build_agent(FakeMCP(), saver1)
            out = await graph1.ainvoke(_initial(), cfg)
            assert "__interrupt__" in out

        async with AsyncExitStack() as s2:
            saver2 = await s2.enter_async_context(AsyncSqliteSaver.from_conn_string(path))
            await saver2.setup()
            graph2 = agent.build_agent(mcp2, saver2)
            out2 = await graph2.ainvoke(Command(resume={"action": "approve"}), cfg)
            assert out2["status"] == "saved"

    asyncio.run(run())
    assert mcp2.saved[0]["name"] == "молоко"
