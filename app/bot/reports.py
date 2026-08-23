import csv
import io
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


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
