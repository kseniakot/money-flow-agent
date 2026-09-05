from app.llm.extract import _fix_prices


def test_fix_prices_recomputes_from_qty_and_unit():
    items = [
        {"name": "арбуз", "qty": 4.658, "unit_price": 1.99, "price": 9.22},
        {"name": "йогурт", "qty": 4, "unit_price": 2.27, "price": 9.08},
    ]
    fixed = _fix_prices(items)
    assert fixed[0]["price"] == 9.27
    assert fixed[1]["price"] == 9.08


def test_fix_prices_skips_when_unit_price_missing():
    items = [{"name": "молоко", "qty": 1, "unit_price": None, "price": 2.9}]
    assert _fix_prices(items)[0]["price"] == 2.9


def test_fix_prices_subtracts_discount():
    items = [{"name": "домик", "qty": 1, "unit_price": 9.99, "discount": 1.20, "price": 9.99}]
    assert _fix_prices(items)[0]["price"] == 8.79
