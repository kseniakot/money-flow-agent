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
