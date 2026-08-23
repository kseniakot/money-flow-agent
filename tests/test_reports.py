from app.bot import reports


def row(product, category, price, currency="BYN", at="2026-08-13 10:00:00", place=None, qty=1, id=1):
    return {
        "id": id,
        "product_name": product,
        "category_name": category,
        "price": price,
        "currency": currency,
        "purchased_at": at,
        "place": place,
        "qty": qty,
        "unit": "шт",
        "unit_price": price,
        "source": "text",
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


def test_build_charts_one_per_currency():
    rows = [
        row("молоко", "молочка", 3.0, "BYN"),
        row("наушники", "техника", 10.0, "USD"),
    ]
    charts = reports.build_charts(rows)
    assert [c[0] for c in charts] == ["BYN", "USD"]
    for _, png in charts:
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_expenses_csv_has_bom_and_header():
    data = reports.expenses_csv([row("молоко", "молочка", 1.92, place="Корона")])
    assert data[:3] == b"\xef\xbb\xbf"
    text = data.decode("utf-8-sig")
    assert "категория" in text.splitlines()[0]
    assert "молоко" in text
    assert "Корона" in text
