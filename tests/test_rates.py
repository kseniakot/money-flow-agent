from app import rates


def setup_function():
    rates.clear_cache()


def test_parse_rate_normalizes_scale():
    assert rates._parse_rate({"Cur_OfficialRate": 33.0, "Cur_Scale": 10}) == 3.3


def test_byn_returns_one_without_fetch():
    assert rates.byn_per_unit("BYN", "2026-08-13") == 1.0


def test_to_usd_with_cached_rates():
    rates._cache[("USD", "2026-08-13")] = 3.0
    rates._cache[("EUR", "2026-08-13")] = 3.3

    assert rates.to_usd(10, "USD", "2026-08-13") == 10.0
    assert rates.to_usd(30, "BYN", "2026-08-13") == 10.0
    assert round(rates.to_usd(100, "EUR", "2026-08-13"), 2) == 110.0


def test_cache_hit_skips_fetch(monkeypatch):
    rates._cache[("USD", "2026-08-13")] = 2.5

    def boom(_cur):
        raise AssertionError("should not fetch on cache hit")

    monkeypatch.setattr(rates, "_fetch", boom)
    assert rates.byn_per_unit("USD", "2026-08-13") == 2.5


def test_fetch_populates_cache(monkeypatch):
    monkeypatch.setattr(rates, "_fetch", lambda _cur: 2.9)
    assert rates.byn_per_unit("USD", "2026-08-13") == 2.9
    assert rates._cache[("USD", "2026-08-13")] == 2.9


def test_raises_when_fetch_fails(monkeypatch):
    def boom(_cur):
        raise rates.URLError("down")

    monkeypatch.setattr(rates, "_fetch", boom)
    try:
        rates.byn_per_unit("USD", "2026-08-13")
        assert False, "expected URLError"
    except rates.URLError:
        pass
