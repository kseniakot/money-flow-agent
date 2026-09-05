
def _money(x) -> str:
    return f"{x:.2f}" if x is not None else "?"


def _num(x) -> str:
    return f"{x:g}"


def _totals(items: list[dict]) -> dict[str, float]:
    by: dict[str, float] = {}
    for it in items:
        by[it["currency"]] = by.get(it["currency"], 0) + (it.get("price") or 0)
    return by


def build_preview(items: list[dict], meta: dict) -> str:
    if not items:
        return "Ничего не распознал. Попробуй иначе."

    source = items[0].get("source", "text")
    lines: list[str] = []

    if source == "receipt":
        head = "🧾 Чек"
        if items[0].get("place"):
            head += f" · {items[0]['place']}"
        lines.append(head)
        if items[0].get("purchased_at"):
            lines.append(f"🕒 {items[0]['purchased_at']}")
    elif source == "bank":
        lines.append("🏦 Списания по карте")
    else:
        label = "Расход (голос)" if source == "voice" else "Расход"
        head = f"🧾 {label} · {items[0].get('purchased_at', '')}"
        if items[0].get("place"):
            head += f" · {items[0]['place']}"
        lines.append(head)

    lines.append("")
    for i, it in enumerate(items, 1):
        line = f"{i}. {it['name']} — {_money(it.get('price'))} {it['currency']}"
        qty = it.get("qty", 1)
        unit = it.get("unit") or "шт"
        if qty != 1 or unit != "шт":
            chunk = f"{_num(qty)} {unit}"
            if qty != 1 and it.get("unit_price") is not None:
                chunk += f" × {_money(it['unit_price'])}"
            line += f" · {chunk}"
        line += f" — {it['category']}"
        if it.get("discount"):
            line += f" (−{_money(it['discount'])} скидка)"
        if source == "bank":
            line += f"\n   · {it.get('purchased_at', '')} · {it.get('place', '')}"
        lines.append(line)

    lines.append("─────────────")
    totals = _totals(items)
    lines.append("Итого: " + ", ".join(f"{_money(v)} {c}" for c, v in totals.items()))

    if source == "receipt" and meta.get("total") is not None:
        items_sum = round(sum((it.get("price") or 0) for it in items), 2)
        total = meta["total"]
        if abs(items_sum - total) > 0.01:
            lines.append(
                f"⚠️ суммы не сходятся: позиции {items_sum}, а к оплате {total}"
            )

    return "\n".join(lines)
