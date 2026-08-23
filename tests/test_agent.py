import asyncio

from langgraph.types import Command

from app import agent
from app.llm import extract


class FakeMCP:
    def __init__(self):
        self.saved = None

    async def save_expenses(self, user_id, items):
        self.saved = items
        return {"inserted": len(items), "ids": list(range(len(items)))}


def base_item(name, price):
    return {
        "name": name,
        "category": "прочее",
        "qty": 1,
        "unit_price": price,
        "price": price,
        "currency": "BYN",
        "purchased_at": "2026-08-15 19:40:00",
        "place": None,
        "source": "text",
    }


def initial():
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


def patch(monkeypatch):
    monkeypatch.setattr(
        extract, "parse", lambda *a, **k: {"items": [base_item("молоко", 1.92)], "meta": {}}
    )
    monkeypatch.setattr(
        extract,
        "revise",
        lambda items, correction, cats: items + [base_item("хлеб", 1.5)],
    )


def test_approve_persists(monkeypatch):
    patch(monkeypatch)
    mcp = FakeMCP()
    graph = agent.build_agent(mcp)
    cfg = {"configurable": {"thread_id": "t1"}}

    async def run():
        out = await graph.ainvoke(initial(), cfg)
        assert "__interrupt__" in out
        out2 = await graph.ainvoke(Command(resume={"action": "approve"}), cfg)
        assert out2["status"] == "saved"
        assert out2["result"]["inserted"] == 1

    asyncio.run(run())
    assert mcp.saved[0]["name"] == "молоко"


def test_revise_then_approve(monkeypatch):
    patch(monkeypatch)
    mcp = FakeMCP()
    graph = agent.build_agent(mcp)
    cfg = {"configurable": {"thread_id": "t2"}}

    async def run():
        await graph.ainvoke(initial(), cfg)
        out = await graph.ainvoke(
            Command(resume={"action": "revise", "correction": "добавь хлеб 1.50"}), cfg
        )
        assert "__interrupt__" in out
        out2 = await graph.ainvoke(Command(resume={"action": "approve"}), cfg)
        assert out2["status"] == "saved"

    asyncio.run(run())
    assert [i["name"] for i in mcp.saved] == ["молоко", "хлеб"]


def test_cancel_does_not_persist(monkeypatch):
    patch(monkeypatch)
    mcp = FakeMCP()
    graph = agent.build_agent(mcp)
    cfg = {"configurable": {"thread_id": "t3"}}

    async def run():
        await graph.ainvoke(initial(), cfg)
        out = await graph.ainvoke(Command(resume={"action": "cancel"}), cfg)
        assert out.get("status") == "cancelled"

    asyncio.run(run())
    assert mcp.saved is None
