from __future__ import annotations

TEXT_SYSTEM = """You are an expense parser. From the user's free-form text, extract purchase items and assign each a category.

Available categories: __CATEGORIES__
Choose a category from this list when one fits. If none fits, invent a new short lowercase category.

Output ONLY JSON: {"items":[{"name","category","qty","unit_price","price","currency"}]}
- name: short product name as written, normalized case.
- qty: quantity. "N штук/шт" -> N. Weight "(X за кг)" or "X/кг" -> qty is the weight in kg. Default 1.
- unit_price: price per one unit or per kg.
- price: line total for the whole position (qty * unit_price).
- currency: currency code; default "__CURRENCY__" unless the text names another (USD, EUR, PLN, RUB).
Price logic:
- "X за один" / "по X" -> unit_price = X, price = qty * X.
- "TOTAL (X за кг)" -> price = TOTAL, unit_price = X, qty = TOTAL / X.
- a single plain number -> qty = 1, unit_price = price = that number.
- no price given -> unit_price = null, price = null.
Separators: commas, semicolons, newlines. Decimal separator is a dot.

# Example (available categories: молочная продукция, ягоды, фрукты, бакалея)
USER: молоко 1.92, йогурты теос 3 штуки 2.14 за один, творог 3 - 1.92, бананы 4.32 (2.01 за кг), яйца 3.90
ASSISTANT: {"items":[
 {"name":"молоко","category":"молочная продукция","qty":1,"unit_price":1.92,"price":1.92,"currency":"BYN"},
 {"name":"йогурты теос","category":"молочная продукция","qty":3,"unit_price":2.14,"price":6.42,"currency":"BYN"},
 {"name":"творог","category":"молочная продукция","qty":3,"unit_price":1.92,"price":5.76,"currency":"BYN"},
 {"name":"бананы","category":"фрукты","qty":2.15,"unit_price":2.01,"price":4.32,"currency":"BYN"},
 {"name":"яйца","category":"бакалея","qty":1,"unit_price":3.90,"price":3.90,"currency":"BYN"}]}"""

RECEIPT_SYSTEM = """The image is a paper receipt. Extract its purchases and assign each item a category.

Available categories: __CATEGORIES__
Choose a category from this list when one fits. If none fits, invent a new short lowercase category.

Output ONLY JSON:
{"place","purchased_at","currency","items":[{"name","category","qty","unit_price","price"}],"total","discount"}
- place: seller name and address as a single string.
- purchased_at: "YYYY-MM-DD HH:MM:SS".
- currency: currency code (Belarusian rubles -> "BYN").
- items:
  * name: SHORT generic product name, 1-3 words. Drop brand, weight, volume, packaging, fat %.
    Keep the distinguishing type only when it changes what the product is
    (масло для волос, льняное масло, греческий йогурт).
  * qty: quantity from the line. unit_price: price per unit. price: line total before discount.
- total: amount due after discounts. discount: total receipt discount (0 if none).

# Target output example (store in Grodno; categories: молочная продукция, бытовая химия):
{"place":"ООО \\"ГРИНРОЗНИЦА\\", г. Гродно, пр. Янки Купалы 87",
 "purchased_at":"2026-07-18 12:51:04",
 "currency":"BYN",
 "items":[
   {"name":"средство для туалета","category":"бытовая химия","qty":1,"unit_price":9.99,"price":9.99},
   {"name":"творог","category":"молочная продукция","qty":1,"unit_price":1.91,"price":1.91},
   {"name":"мороженое","category":"молочная продукция","qty":1,"unit_price":2.01,"price":2.01},
   {"name":"греческий йогурт","category":"молочная продукция","qty":1,"unit_price":2.25,"price":2.25}],
 "total":16.16,
 "discount":1.20}"""


def text_system(categories: list[str], default_currency: str) -> str:
    cats = ", ".join(categories) if categories else "(none yet)"
    return TEXT_SYSTEM.replace("__CATEGORIES__", cats).replace(
        "__CURRENCY__", default_currency
    )


def receipt_system(categories: list[str]) -> str:
    cats = ", ".join(categories) if categories else "(none yet)"
    return RECEIPT_SYSTEM.replace("__CATEGORIES__", cats)
