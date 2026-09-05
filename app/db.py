import calendar
import sqlite3
from datetime import datetime
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

CREATE TABLE IF NOT EXISTS wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    currency TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('spending', 'savings')),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (user_id, currency, kind)
);

CREATE TABLE IF NOT EXISTS wallet_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_id INTEGER NOT NULL REFERENCES wallets(id),
    kind TEXT NOT NULL CHECK (kind IN ('deposit', 'correction')),
    amount NUMERIC NOT NULL,
    comment TEXT,
    occurred_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    wallet_id INTEGER NOT NULL REFERENCES wallets(id),
    name TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL,
    start_date TEXT NOT NULL,
    day_of_month INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    comment TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    last_charged_ym TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    wallet_id INTEGER REFERENCES wallets(id),
    subscription_id INTEGER REFERENCES subscriptions(id),
    qty NUMERIC NOT NULL DEFAULT 1,
    unit TEXT NOT NULL DEFAULT 'шт',
    unit_price NUMERIC,
    discount NUMERIC NOT NULL DEFAULT 0,
    price NUMERIC,
    currency TEXT NOT NULL,
    purchased_at TEXT NOT NULL,
    place TEXT,
    source TEXT NOT NULL CHECK (source IN ('text', 'voice', 'receipt', 'subscription', 'bank')),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    text TEXT,
    file_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


def get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = str(db_path or config.db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_MIGRATIONS = [
    ("expenses", "unit_price", "NUMERIC", None),
    ("expenses", "unit", "TEXT NOT NULL DEFAULT 'шт'", None),
    ("expenses", "discount", "NUMERIC NOT NULL DEFAULT 0", None),
    (
        "subscriptions",
        "start_date",
        "TEXT",
        "UPDATE subscriptions SET start_date = date(created_at) WHERE start_date IS NULL",
    ),
    ("queue", "file_id", "TEXT", None),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, decl, backfill in _MIGRATIONS:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            if backfill:
                conn.execute(backfill)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
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


def get_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row(row)


def set_default_currency(
    conn: sqlite3.Connection, user_id: int, currency: str
) -> None:
    conn.execute(
        "UPDATE users SET default_currency = ? WHERE id = ?", (currency, user_id)
    )
    conn.commit()


def delete_expense(conn: sqlite3.Connection, expense_id: int) -> None:
    conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    conn.commit()


def get_expense(conn: sqlite3.Connection, expense_id: int, user_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT e.id, e.qty, e.unit, e.unit_price, e.discount, e.price, e.currency,
               e.purchased_at, e.place, e.source,
               p.name AS product_name, c.name AS category_name
        FROM expenses e
        JOIN products p ON p.id = e.product_id
        JOIN categories c ON c.id = p.category_id
        WHERE e.id = ? AND e.user_id = ?
        """,
        (expense_id, user_id),
    ).fetchone()
    return _row(row)




def last_expense(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT e.id, e.price, e.currency, p.name AS product_name
        FROM expenses e
        JOIN products p ON p.id = e.product_id
        WHERE e.user_id = ?
        ORDER BY e.id DESC LIMIT 1
        """,
        (user_id,),
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
        wallet = get_or_create_wallet(conn, user_id, it["currency"], "spending")
        cur = conn.execute(
            """
            INSERT INTO expenses
                (user_id, product_id, wallet_id, subscription_id, qty, unit, unit_price,
                 discount, price, currency, purchased_at, place, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                it["product_id"],
                wallet["id"],
                it.get("subscription_id"),
                it.get("qty", 1),
                it.get("unit", "шт"),
                it.get("unit_price"),
                it.get("discount", 0),
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


def save_expenses(
    conn: sqlite3.Connection, user_id: int, items: list[dict]
) -> dict:
    expense_items = []
    for it in items:
        category = create_category(conn, it["category"])
        product = upsert_product(conn, it["name"], category["id"])
        expense_items.append(
            {
                "product_id": product["id"],
                "qty": it.get("qty", 1),
                "unit": it.get("unit", "шт"),
                "unit_price": it.get("unit_price"),
                "discount": it.get("discount", 0),
                "price": it.get("price"),
                "currency": it["currency"],
                "purchased_at": it["purchased_at"],
                "place": it.get("place"),
                "source": it["source"],
            }
        )
    return add_expenses(conn, user_id, expense_items)


def query_expenses(
    conn: sqlite3.Connection, start: str, end: str, user_id: int
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            e.id, e.qty, e.unit, e.unit_price, e.discount, e.price, e.currency,
            e.purchased_at, e.place, e.source,
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


def get_or_create_wallet(
    conn: sqlite3.Connection, user_id: int, currency: str, kind: str = "spending"
) -> dict:
    conn.execute(
        """
        INSERT INTO wallets (user_id, currency, kind) VALUES (?, ?, ?)
        ON CONFLICT(user_id, currency, kind) DO NOTHING
        """,
        (user_id, currency, kind),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM wallets WHERE user_id = ? AND currency = ? AND kind = ?",
        (user_id, currency, kind),
    ).fetchone()
    return _row(row)


def wallet_balance(conn: sqlite3.Connection, wallet_id: int) -> float:
    row = conn.execute(
        """
        SELECT
            COALESCE((SELECT SUM(amount) FROM wallet_movements WHERE wallet_id = ?), 0)
          - COALESCE((SELECT SUM(price) FROM expenses WHERE wallet_id = ?), 0)
          AS balance
        """,
        (wallet_id, wallet_id),
    ).fetchone()
    return float(row["balance"])


def list_wallets(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM wallets WHERE user_id = ? ORDER BY kind, currency",
        (user_id,),
    ).fetchall()
    result = []
    for r in rows:
        w = dict(r)
        w["balance"] = wallet_balance(conn, w["id"])
        result.append(w)
    return result


def add_movement(
    conn: sqlite3.Connection,
    wallet_id: int,
    kind: str,
    amount: float,
    comment: str | None = None,
    occurred_at: str | None = None,
) -> dict:
    cur = conn.execute(
        """
        INSERT INTO wallet_movements (wallet_id, kind, amount, comment, occurred_at)
        VALUES (?, ?, ?, ?, COALESCE(?, datetime('now', 'localtime')))
        """,
        (wallet_id, kind, amount, comment, occurred_at),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM wallet_movements WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _row(row)


def exchange(
    conn: sqlite3.Connection,
    user_id: int,
    from_currency: str,
    to_currency: str,
    amount: float,
    rate: float,
    kind: str = "spending",
) -> dict:
    received = round(amount * rate, 2)
    src = get_or_create_wallet(conn, user_id, from_currency, kind)
    dst = get_or_create_wallet(conn, user_id, to_currency, kind)
    add_movement(conn, src["id"], "deposit", -amount, f"обмен → {to_currency} @{rate:g}")
    add_movement(conn, dst["id"], "deposit", received, f"обмен ← {from_currency} @{rate:g}")
    return {
        "received": received,
        "from_balance": wallet_balance(conn, src["id"]),
        "to_balance": wallet_balance(conn, dst["id"]),
    }


def list_exchanges(conn: sqlite3.Connection, user_id: int, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """
        SELECT m.amount, m.comment, m.occurred_at, w.currency
        FROM wallet_movements m
        JOIN wallets w ON w.id = m.wallet_id
        WHERE w.user_id = ? AND m.comment LIKE 'обмен%'
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def create_subscription(
    conn: sqlite3.Connection,
    user_id: int,
    name: str,
    amount: float,
    currency: str,
    start_date: str,
    comment: str | None = None,
) -> dict:
    wallet = get_or_create_wallet(conn, user_id, currency, "spending")
    day_of_month = int(start_date[8:10])
    cur = conn.execute(
        """
        INSERT INTO subscriptions
            (user_id, wallet_id, name, amount, currency, start_date, day_of_month, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, wallet["id"], name, amount, currency, start_date, day_of_month, comment),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _row(row)


def list_subscriptions(
    conn: sqlite3.Connection, user_id: int, active_only: bool = True
) -> list[dict]:
    q = "SELECT * FROM subscriptions WHERE user_id = ?"
    if active_only:
        q += " AND active = 1"
    q += " ORDER BY day_of_month"
    rows = conn.execute(q, (user_id,)).fetchall()
    return [dict(r) for r in rows]


def deactivate_subscription(conn: sqlite3.Connection, subscription_id: int) -> None:
    conn.execute(
        "UPDATE subscriptions SET active = 0 WHERE id = ?", (subscription_id,)
    )
    conn.commit()


def due_subscriptions(conn: sqlite3.Connection, on_date: datetime) -> list[dict]:
    ym = on_date.strftime("%Y-%m")
    days_in_month = calendar.monthrange(on_date.year, on_date.month)[1]
    on_str = on_date.strftime("%Y-%m-%d")
    rows = conn.execute(
        """
        SELECT * FROM subscriptions
        WHERE active = 1
          AND date(start_date) <= date(?)
          AND (last_charged_ym IS NULL OR last_charged_ym != ?)
          AND date(
                printf('%s-%02d', ?,
                       CASE WHEN day_of_month <= ? THEN day_of_month ELSE 1 END)
              ) <= date(?)
        """,
        (on_str, ym, ym, days_in_month, on_str),
    ).fetchall()
    return [dict(r) for r in rows]


def charge_subscription(
    conn: sqlite3.Connection, subscription: dict, purchased_at: str
) -> dict:
    category = create_category(conn, "подписки")
    product = upsert_product(conn, subscription["name"], category["id"])
    res = add_expenses(
        conn,
        user_id=subscription["user_id"],
        items=[
            {
                "product_id": product["id"],
                "subscription_id": subscription["id"],
                "qty": 1,
                "price": subscription["amount"],
                "currency": subscription["currency"],
                "purchased_at": purchased_at,
                "place": None,
                "source": "subscription",
            }
        ],
    )
    ym = purchased_at[:7]
    conn.execute(
        "UPDATE subscriptions SET last_charged_ym = ? WHERE id = ?",
        (ym, subscription["id"]),
    )
    conn.commit()
    return {"expense_id": res["ids"][0], "ym": ym}


def enqueue(
    conn: sqlite3.Connection,
    chat_id: int,
    user_id: int,
    source: str,
    text: str | None,
    file_id: str | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO queue (chat_id, user_id, source, text, file_id) VALUES (?, ?, ?, ?, ?)",
        (chat_id, user_id, source, text, file_id),
    )
    conn.commit()
    return cur.lastrowid


def queue_front(conn: sqlite3.Connection, chat_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM queue WHERE chat_id = ? ORDER BY id LIMIT 1", (chat_id,)
    ).fetchone()
    return _row(row)


def queue_delete(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM queue WHERE id = ?", (item_id,))
    conn.commit()


def queue_count(conn: sqlite3.Connection, chat_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM queue WHERE chat_id = ?", (chat_id,)
    ).fetchone()[0]


def queue_chats(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT DISTINCT chat_id FROM queue")]
