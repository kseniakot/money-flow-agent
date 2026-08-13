from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from app import db
from app.config import config

mcp = MCPServer("expenses")

_db_path = config.db_path


def _conn():
    return db.get_conn(_db_path)


def init() -> None:
    conn = _conn()
    db.init_db(conn)
    conn.close()


init()


@mcp.resource("categories://list")
def categories_list() -> list[dict]:
    conn = _conn()
    try:
        return db.list_categories(conn)
    finally:
        conn.close()


@mcp.tool()
def save_expenses(
    user_id: int,
    items: list[dict],
    currency: str,
    purchased_at: str,
    source: str,
    place: str | None = None,
) -> dict:
    conn = _conn()
    try:
        return db.save_expenses(
            conn, user_id, items, currency, purchased_at, source, place
        )
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run()
