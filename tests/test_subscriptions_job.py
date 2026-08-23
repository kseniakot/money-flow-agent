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
    db.create_subscription(conn, user["id"], "Netflix", 12.99, "USD", "2026-08-15")

    now = datetime(2026, 8, 15, 9, 0, 0)
    charged = bot._charge_due(now, path)
    assert len(charged) == 1
    assert charged[0]["tg"] == 555

    wallet = db.get_or_create_wallet(conn, user["id"], "USD", "spending")
    assert db.wallet_balance(conn, wallet["id"]) == -12.99

    assert bot._charge_due(now, path) == []


def test_day_31_rolls_to_first_of_short_month(tmp_path):
    path, conn = setup(tmp_path)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    db.create_subscription(conn, user["id"], "Gym", 30.0, "BYN", "2026-01-31")

    # September has 30 days -> the 31st is absent -> charge on Sep 1
    assert len(bot._charge_due(datetime(2026, 9, 1, 9, 0, 0), path)) == 1
    # not on the 30th
    assert bot._charge_due(datetime(2026, 9, 30, 9, 0, 0), path) == []


def test_catches_up_missed_day(tmp_path):
    path, conn = setup(tmp_path)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    db.create_subscription(conn, user["id"], "Netflix", 12.99, "USD", "2026-08-05")

    # bot was offline on the 5th and only runs on the 10th -> catch up
    assert len(bot._charge_due(datetime(2026, 8, 10, 9, 0, 0), path)) == 1
    # but not twice in the same month
    assert bot._charge_due(datetime(2026, 8, 15, 9, 0, 0), path) == []


def test_not_charged_before_start_or_other_day(tmp_path):
    path, conn = setup(tmp_path)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    db.create_subscription(conn, user["id"], "Netflix", 12.99, "USD", "2026-08-15")

    assert bot._charge_due(datetime(2026, 8, 14, 9, 0, 0), path) == []
    assert bot._charge_due(datetime(2026, 7, 15, 9, 0, 0), path) == []


def test_only_sub_id_filters(tmp_path):
    path, conn = setup(tmp_path)
    user = db.upsert_user(conn, tg_user_id=1, tg_username="me")
    a = db.create_subscription(conn, user["id"], "A", 5.0, "BYN", "2026-08-15")
    db.create_subscription(conn, user["id"], "B", 7.0, "BYN", "2026-08-15")

    charged = bot._charge_due(datetime(2026, 8, 15, 9, 0, 0), path, a["id"])
    assert len(charged) == 1
    assert charged[0]["sub"]["name"] == "A"
