import csv
import io
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


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


def expenses_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["id", "дата", "категория", "продукт", "кол-во", "единица",
         "цена_за_ед", "сумма", "валюта", "место", "источник"]
    )
    for r in rows:
        writer.writerow(
            [r["id"], r["purchased_at"], r["category_name"], r["product_name"],
             r["qty"], r["unit"], r["unit_price"], r["price"], r["currency"],
             r["place"] or "", r["source"]]
        )
    return buf.getvalue().encode("utf-8-sig")


def build_charts(rows: list[dict]) -> list[tuple[str, bytes]]:
    by_cur: dict[str, dict[str, float]] = {}
    for r in rows:
        cats = by_cur.setdefault(r["currency"], defaultdict(float))
        cats[r["category_name"]] += r["price"] or 0

    charts = []
    for cur in sorted(by_cur):
        data = sorted(by_cur[cur].items(), key=lambda x: x[1])
        labels = [d[0] for d in data]
        values = [d[1] for d in data]

        fig, ax = plt.subplots(figsize=(7, max(3, 0.5 * len(labels) + 1)))
        bars = ax.barh(labels, values, color="#0f7d6b")
        ax.set_xlabel(cur)
        ax.set_title(f"Расходы по категориям ({cur})")
        ax.spines[["top", "right"]].set_visible(False)
        for bar, v in zip(bars, values):
            ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f" {v:.2f}", va="center")
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        charts.append((cur, buf.getvalue()))
    return charts
