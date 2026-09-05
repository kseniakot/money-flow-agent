from app.bot.render import build_preview


def it(name, price, currency="BYN", qty=1, unit_price=None, unit="шт", source="text", place=None, at="2026-08-15 19:40:00", category="прочее"):
    return {
        "name": name,
        "category": category,
        "qty": qty,
        "unit": unit,
        "unit_price": unit_price if unit_price is not None else price,
        "price": price,
        "currency": currency,
        "purchased_at": at,
        "place": place,
        "source": source,
    }


def test_text_preview_lists_items_and_total():
    out = build_preview(
        [it("молоко", 1.92), it("бананы", 4.32, qty=2.15, unit_price=2.01, unit="кг")], {}
    )
    assert "молоко — 1.92 BYN" in out
    assert "2.15 кг × 2.01" in out
    assert "Итого: 6.24 BYN" in out


def test_single_kg_shows_unit():
    out = build_preview([it("арахисовая паста", 18.93, qty=1, unit="кг")], {})
    assert "1 кг" in out


def test_default_piece_qty_one_hidden():
    out = build_preview([it("молоко", 1.92, qty=1, unit="шт")], {})
    assert " · 1 шт" not in out


def test_mixed_currency_totals():
    out = build_preview([it("молоко", 2.0), it("наушники", 30.0, currency="USD")], {})
    assert "2.00 BYN" in out and "30.00 USD" in out


def test_receipt_checksum_warns_on_mismatch():
    items = [it("творог", 1.91, source="receipt", place="Shop", at="2026-07-18 12:51:04")]
    out = build_preview(items, {"total": 5.0, "discount": 0, "items_sum": 1.91})
    assert "⚠️" in out
    assert "🧾 Чек · Shop" in out


def test_receipt_discount_shown_and_net_checksum():
    item = it("средство", 8.79, source="receipt", place="Grin", at="2026-07-18 12:51:04")
    item["unit_price"] = 9.99
    item["discount"] = 1.20
    out = build_preview([item], {"total": 8.79, "discount": 1.20})
    assert "(−1.20 скидка)" in out
    assert "⚠️" not in out


def test_bank_shows_place_per_line():
    items = [it("отвертки", 9.85, source="bank", place="OZON", at="2026-08-13 20:37:00")]
    out = build_preview(items, {})
    assert "🏦" in out
    assert "OZON" in out
