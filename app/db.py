from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER UNIQUE NOT NULL,
    tg_username TEXT,
    default_currency TEXT NOT NULL DEFAULT 'BYN',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty NUMERIC NOT NULL DEFAULT 1,
    price NUMERIC,
    currency TEXT NOT NULL,
    purchased_at TEXT NOT NULL,
    place TEXT,
    source TEXT NOT NULL CHECK (source IN ('text', 'voice', 'receipt')),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


def get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = str(db_path or config.db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def upsert_user(
    conn: sqlite3.Connection,
    tg_user_id: int,
    tg_username: str | None,
    default_currency: str | None = None,
) -> dict:
    conn.execute(
        """
        INSERT INTO users (tg_user_id, tg_username, default_currency)
        VALUES (?, ?, COALESCE(?, 'BYN'))
        ON CONFLICT(tg_user_id) DO UPDATE SET
            tg_username = excluded.tg_username
        """,
        (tg_user_id, tg_username, default_currency),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM users WHERE tg_user_id = ?", (tg_user_id,)
    ).fetchone()
    return _row(row)


def list_categories(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name FROM categories ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def create_category(conn: sqlite3.Connection, name: str) -> dict:
    conn.execute(
        "INSERT INTO categories (name) VALUES (?) ON CONFLICT(name) DO NOTHING",
        (name,),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM categories WHERE name = ?", (name,)).fetchone()
    return _row(row)


def find_product(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute(
        """
        SELECT p.id, p.name, p.category_id, c.name AS category_name
        FROM products p
        JOIN categories c ON c.id = p.category_id
        WHERE p.name = ?
        """,
        (name,),
    ).fetchone()
    return _row(row)


def upsert_product(conn: sqlite3.Connection, name: str, category_id: int) -> dict:
    conn.execute(
        """
        INSERT INTO products (name, category_id) VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET category_id = excluded.category_id
        """,
        (name, category_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM products WHERE name = ?", (name,)).fetchone()
    return _row(row)


def add_expenses(
    conn: sqlite3.Connection, user_id: int, items: list[dict]
) -> dict:
    ids: list[int] = []
    for it in items:
        cur = conn.execute(
            """
            INSERT INTO expenses
                (user_id, product_id, qty, price, currency, purchased_at, place, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                it["product_id"],
                it.get("qty", 1),
                it.get("price"),
                it["currency"],
                it["purchased_at"],
                it.get("place"),
                it["source"],
            ),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return {"inserted": len(ids), "ids": ids}


def query_expenses(
    conn: sqlite3.Connection, start: str, end: str, user_id: int
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            e.id, e.qty, e.price, e.currency, e.purchased_at, e.place, e.source,
            p.name AS product_name,
            c.name AS category_name
        FROM expenses e
        JOIN products p ON p.id = e.product_id
        JOIN categories c ON c.id = p.category_id
        WHERE e.user_id = ?
          AND date(e.purchased_at) BETWEEN date(?) AND date(?)
        ORDER BY c.name, e.purchased_at
        """,
        (user_id, start, end),
    ).fetchall()
    return [dict(r) for r in rows]
