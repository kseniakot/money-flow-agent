from app import db, rates


def make_conn():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    return conn


def test_parse_rate_normalizes_scale():
    assert rates._parse_rate({"Cur_OfficialRate": 33.0, "Cur_Scale": 10}) == 3.3


def test_byn_returns_one_without_fetch():
    conn = make_conn()
    assert rates.byn_per_unit(conn, "BYN", "2026-08-13") == 1.0


def test_to_usd_with_cached_rates():
    conn = make_conn()
    rates.upsert_rate(conn, "2026-08-13", "USD", 3.0)
    rates.upsert_rate(conn, "2026-08-13", "EUR", 3.3)

    assert rates.to_usd(conn, 10, "USD", "2026-08-13") == 10.0
    assert rates.to_usd(conn, 30, "BYN", "2026-08-13") == 10.0
    assert round(rates.to_usd(conn, 100, "EUR", "2026-08-13"), 2) == 110.0
