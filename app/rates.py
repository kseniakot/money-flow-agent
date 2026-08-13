from __future__ import annotations

import json
import sqlite3
from datetime import date as date_cls
from urllib.request import urlopen

NBRB_URL = "https://api.nbrb.by/exrates/rates/{cur}?parammode=2"


def _today() -> str:
    return date_cls.today().isoformat()


def _parse_rate(payload: dict) -> float:
    return float(payload["Cur_OfficialRate"]) / float(payload["Cur_Scale"])


def _fetch(currency: str) -> float:
    with urlopen(NBRB_URL.format(cur=currency), timeout=10) as resp:
        payload = json.loads(resp.read().decode())
    return _parse_rate(payload)


def cached_byn_per_unit(
    conn: sqlite3.Connection, currency: str, on_date: str
) -> float | None:
    row = conn.execute(
        "SELECT byn_per_unit FROM rates WHERE date = ? AND currency = ?",
        (on_date, currency),
    ).fetchone()
    return float(row["byn_per_unit"]) if row else None


def upsert_rate(
    conn: sqlite3.Connection, on_date: str, currency: str, byn_per_unit: float
) -> None:
    conn.execute(
        """
        INSERT INTO rates (date, currency, byn_per_unit) VALUES (?, ?, ?)
        ON CONFLICT(date, currency) DO UPDATE SET byn_per_unit = excluded.byn_per_unit
        """,
        (on_date, currency, byn_per_unit),
    )
    conn.commit()


def byn_per_unit(
    conn: sqlite3.Connection, currency: str, on_date: str | None = None
) -> float:
    currency = currency.upper()
    if currency == "BYN":
        return 1.0
    on_date = on_date or _today()
    cached = cached_byn_per_unit(conn, currency, on_date)
    if cached is not None:
        return cached
    value = _fetch(currency)
    upsert_rate(conn, on_date, currency, value)
    return value


def to_usd(
    conn: sqlite3.Connection,
    amount: float,
    currency: str,
    on_date: str | None = None,
) -> float:
    on_date = on_date or _today()
    src = byn_per_unit(conn, currency, on_date)
    usd = byn_per_unit(conn, "USD", on_date)
    return amount * src / usd
