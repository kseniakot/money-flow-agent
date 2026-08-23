import asyncio

from app import db
from app.mcp_client import MCPClient


def test_client_reads_resource_and_saves(tmp_path):
    path = str(tmp_path / "client.sqlite")
    conn = db.get_conn(path)
    db.init_db(conn)
    db.upsert_user(conn, tg_user_id=1, tg_username="me")

    async def run():
        async with MCPClient(db_path=path) as c:
            assert await c.categories() == []
            res = await c.save_expenses(
                user_id=1,
                items=[
                    {
                        "name": "молоко",
                        "category": "молочка",
                        "qty": 1,
                        "unit_price": 1.9,
                        "price": 1.9,
                        "currency": "BYN",
                        "purchased_at": "2026-08-15 10:00:00",
                        "place": None,
                        "source": "text",
                    }
                ],
            )
            assert res["inserted"] == 1
            assert await c.categories() == ["молочка"]

    asyncio.run(run())
