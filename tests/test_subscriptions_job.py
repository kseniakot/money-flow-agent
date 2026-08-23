from datetime import datetime

from app import db
from app.bot import handlers as bot


def setup(tmp_path):
    path = str(tmp_path / "subs.sqlite")
    conn = db.get_conn(path)
    db.init_db(conn)
    return path, conn


def test_charges_due_subscription_once(tmp_path):
    path, conn = setup(tmp_path)
    user = db.upsert_user(conn, tg_user_id=555, tg_username="me")
    db.create_subscription(conn, user["id"], "Netflix", 12.99, "USD", 15)

    now = datetime(2026, 8, 15, 9, 0, 0)
    charged = bot._charge_due(now, path)
    assert len(charged) == 1
    assert charged[0]["tg"] == 555

    wallet = db.get_or_create_wallet(conn, user["id"], "USD", "spending")
    assert db.wallet_balance(conn, wallet["id"]) == -12.99

    assert bot._charge_due(now, path) == []


def test_day_31_charged_on_last_day_of_short_month(tmp_path):
    path, conn = setup(tmp_path)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    db.create_subscription(conn, user["id"], "Gym", 30.0, "BYN", 31)

    now = datetime(2026, 9, 30, 9, 0, 0)
    charged = bot._charge_due(now, path)
    assert len(charged) == 1


def test_not_charged_on_other_day(tmp_path):
    path, conn = setup(tmp_path)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    db.create_subscription(conn, user["id"], "Netflix", 12.99, "USD", 15)

    assert bot._charge_due(datetime(2026, 8, 14, 9, 0, 0), path) == []
