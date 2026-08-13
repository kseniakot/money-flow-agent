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
def find_product(name: str) -> dict | None:
    conn = _conn()
    try:
        return db.find_product(conn, name)
    finally:
        conn.close()


@mcp.tool()
def create_category(name: str) -> dict:
    conn = _conn()
    try:
        return db.create_category(conn, name)
    finally:
        conn.close()


@mcp.tool()
def upsert_product(name: str, category_id: int) -> dict:
    conn = _conn()
    try:
        return db.upsert_product(conn, name, category_id)
    finally:
        conn.close()


@mcp.tool()
def add_expenses(user_id: int, items: list[dict]) -> dict:
    conn = _conn()
    try:
        return db.add_expenses(conn, user_id, items)
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run()
