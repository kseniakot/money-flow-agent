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
            q = r.get("qty", 1)
            u = r.get("unit") or "шт"
            qty = f" · {q:g} {u}" if (q != 1 or u != "шт") else ""
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
    data = [
        (name, sum(rates.to_usd(v, cur) for cur, v in c["totals"].items()))
        for name, c in cats.items()
    ]
    data.sort(key=lambda x: x[1])
    labels = [d[0] for d in data]
    values = [d[1] for d in data]

    fig, ax = plt.subplots(figsize=(7, max(3, 0.5 * len(labels) + 1)))
    bars = ax.barh(labels, values, color="#0f7d6b")
    ax.set_xlabel("USD")
    ax.set_title("Расходы по категориям (USD)")
    ax.spines[["top", "right"]].set_visible(False)
    for bar, v in zip(bars, values):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f" {v:.0f}", va="center")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return buf.getvalue()
