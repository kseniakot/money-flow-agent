from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app import prompts
from app.llm import get_llm

_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def _json(raw: str) -> dict:
    return json.loads(_FENCE.sub("", raw.strip()).strip())


def _content(text: str, image: str | None):
    if image is None:
        return text
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image}},
    ]


def _invoke(system: str, text: str, image: str | None) -> dict:
    llm = get_llm()
    resp = llm.invoke([SystemMessage(system), HumanMessage(content=_content(text, image))])
    return _json(resp.content)


def parse(
    source: str,
    text: str,
    image: str | None,
    categories: list[str],
    default_currency: str,
    now: str,
    today: str,
) -> dict:
    if source in ("text", "voice"):
        data = _invoke(prompts.text_system(categories, default_currency), text, None)
        items = [
            {**it, "purchased_at": now, "place": None, "source": source}
            for it in data["items"]
        ]
        return {"items": items, "meta": {}}

    if source == "receipt":
        data = _invoke(prompts.receipt_system(categories), text or "Parse this receipt.", image)
        items = [
            {
                **it,
                "currency": data["currency"],
                "purchased_at": data["purchased_at"],
                "place": data["place"],
                "source": "receipt",
            }
            for it in data["items"]
        ]
        meta = {
            "total": data.get("total"),
            "discount": data.get("discount", 0),
            "items_sum": round(sum(i.get("price") or 0 for i in items), 2),
        }
        return {"items": items, "meta": meta}

    if source == "bank":
        data = _invoke(prompts.bank_system(categories, today), text, image)
        items = [{**it, "source": "bank"} for it in data["items"]]
        return {"items": items, "meta": {}}

    raise ValueError(f"unknown source: {source}")


def revise(items: list[dict], correction: str, categories: list[str]) -> list[dict]:
    system = prompts.revise_system(categories)
    payload = json.dumps({"items": items}, ensure_ascii=False)
    llm = get_llm()
    resp = llm.invoke(
        [
            SystemMessage(system),
            HumanMessage(content=f"CURRENT: {payload}\nCORRECTION: {correction}"),
        ]
    )
    return _json(resp.content)["items"]
