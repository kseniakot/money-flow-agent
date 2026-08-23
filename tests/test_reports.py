from app import rates
from app.bot import reports


def row(product, category, price, currency="BYN", at="2026-08-13 10:00:00", place=None, qty=1):
    return {
        "product_name": product,
        "category_name": category,
        "price": price,
        "currency": currency,
        "purchased_at": at,
        "place": place,
        "qty": qty,
        "unit_price": price,
    }


def test_report_text_groups_by_category():
    rows = [
        row("молоко", "молочка", 1.92),
        row("масло", "молочка", 4.65),
        row("наушники", "техника", 30.0, "USD", place="OZON"),
    ]
    out = reports.build_report_text(rows, "2026-08-01", "2026-08-31")
    assert "▸ молочка: 6.57 BYN" in out
    assert "▸ техника: 30.00 USD" in out
    assert "наушники" in out and "OZON" in out
    assert "Итого: 6.57 BYN, 30.00 USD" in out


def test_report_empty():
    assert "расходов нет" in reports.build_report_text([], "2026-08-01", "2026-08-31")


def test_chart_returns_png(monkeypatch):
    rates.clear_cache()
    rates._cache[("USD", rates._today())] = 3.0
    rows = [row("молоко", "молочка", 3.0), row("наушники", "техника", 10.0, "USD")]
    png = reports.build_chart(rows)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
