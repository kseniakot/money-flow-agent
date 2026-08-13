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
def query_expenses(start: str, end: str, user_id: int) -> list[dict]:
    conn = _conn()
    try:
        return db.query_expenses(conn, start, end, user_id)
    finally:
        conn.close()


@mcp.tool()
def wallet_balances(user_id: int) -> list[dict]:
    conn = _conn()
    try:
        return db.list_wallets(conn, user_id)
    finally:
        conn.close()


@mcp.tool()
def list_subscriptions(user_id: int, active_only: bool = True) -> list[dict]:
    conn = _conn()
    try:
        return db.list_subscriptions(conn, user_id, active_only)
    finally:
        conn.close()


@mcp.tool()
def upsert_user(
    tg_user_id: int, tg_username: str | None, default_currency: str | None = None
) -> dict:
    conn = _conn()
    try:
        return db.upsert_user(conn, tg_user_id, tg_username, default_currency)
    finally:
        conn.close()


@mcp.tool()
def get_or_create_wallet(
    user_id: int, currency: str, kind: str = "spending"
) -> dict:
    conn = _conn()
    try:
        return db.get_or_create_wallet(conn, user_id, currency, kind)
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


@mcp.tool()
def add_movement(
    wallet_id: int,
    kind: str,
    amount: float,
    comment: str | None = None,
    occurred_at: str | None = None,
) -> dict:
    conn = _conn()
    try:
        return db.add_movement(conn, wallet_id, kind, amount, comment, occurred_at)
    finally:
        conn.close()


@mcp.tool()
def create_subscription(
    user_id: int,
    name: str,
    amount: float,
    currency: str,
    day_of_month: int,
    comment: str | None = None,
) -> dict:
    conn = _conn()
    try:
        return db.create_subscription(
            conn, user_id, name, amount, currency, day_of_month, comment
        )
    finally:
        conn.close()


@mcp.tool()
def deactivate_subscription(subscription_id: int) -> dict:
    conn = _conn()
    try:
        db.deactivate_subscription(conn, subscription_id)
        return {"deactivated": subscription_id}
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run()
