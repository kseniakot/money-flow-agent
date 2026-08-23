import io
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app import rates  # noqa: E402


def _by_category(rows: list[dict]) -> dict:
    cats: dict[str, dict] = {}
    for r in rows:
        c = cats.setdefault(r["category_name"], {"items": [], "totals": defaultdict(float)})
        c["items"].append(r)
        c["totals"][r["currency"]] += r["price"] or 0
    return cats


def _totals(rows: list[dict]) -> dict[str, float]:
    by: dict[str, float] = defaultdict(float)
    for r in rows:
        by[r["currency"]] += r["price"] or 0
    return by


def build_report_text(rows: list[dict], start: str, end: str) -> str:
    if not rows:
        return f"За {start} — {end} расходов нет."

    cats = _by_category(rows)
    lines = [f"📊 Отчёт {start} — {end}", ""]
    for name in sorted(cats):
        c = cats[name]
        tot = ", ".join(f"{v:.2f} {cur}" for cur, v in c["totals"].items())
        lines.append(f"▸ {name}: {tot}")
        for r in c["items"]:
            when = r["purchased_at"][:16]
            place = f" · {r['place']}" if r.get("place") else ""
            qty = f" ×{r['qty']:g}" if r.get("qty", 1) != 1 else ""
            lines.append(
                f"   {r['product_name']}{qty} — {r['price']:.2f} {r['currency']}"
                f" · {when}{place}"
            )
        lines.append("")

    grand = _totals(rows)
    lines.append("Итого: " + ", ".join(f"{v:.2f} {cur}" for cur, v in grand.items()))
    return "\n".join(lines)


def build_chart(rows: list[dict]) -> bytes:
    cats = _by_category(rows)
    labels, sizes = [], []
    for name, c in cats.items():
        usd = sum(rates.to_usd(v, cur) for cur, v in c["totals"].items())
        labels.append(name)
        sizes.append(usd)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90)
    ax.set_title("Расходы по категориям (USD)")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120)
    plt.close(fig)
    return buf.getvalue()
