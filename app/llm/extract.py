import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import prompts
from app.llm.client import get_llm

log = logging.getLogger(__name__)

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
    log.info("→ model: input=%r image=%s", text[:120], bool(image))
    resp = llm.invoke([SystemMessage(system), HumanMessage(content=_content(text, image))])
    log.debug("← model raw: %s", resp.content[:800])
    data = _json(resp.content)
    log.info("← model: %d items", len(data.get("items", [])))
    return data


def parse(
    source: str,
    text: str,
    image: str | None,
    categories: list[str],
    default_currency: str,
    now: str,
    today: str,
) -> dict:
    log.info("parse: source=%s categories=%d", source, len(categories))
    if source in ("text", "voice"):
        data = _invoke(prompts.text_system(categories, default_currency), text, None)
        place = data.get("place")
        items = [
            {**it, "purchased_at": now, "place": place, "source": source}
            for it in data["items"]
        ]
        return {"items": items, "meta": {}}

    if source == "photo":
        data = _invoke(prompts.photo_system(categories, today), text or "", image)
        kind = data.get("kind", "receipt")
        items = [{**it, "source": kind} for it in data["items"]]
        if kind == "receipt":
            meta = {
                "total": data.get("total"),
                "discount": data.get("discount", 0),
            }
        else:
            meta = {}
        return {"items": items, "meta": meta}

    raise ValueError(f"unknown source: {source}")


def revise(items: list[dict], correction: str, categories: list[str], today: str) -> list[dict]:
    log.info("revise: %r on %d items", correction[:120], len(items))
    system = prompts.revise_system(categories, today)
    payload = json.dumps({"items": items}, ensure_ascii=False)
    llm = get_llm()
    resp = llm.invoke(
        [
            SystemMessage(system),
            HumanMessage(content=f"CURRENT: {payload}\nCORRECTION: {correction}"),
        ]
    )
    result = _json(resp.content)["items"]
    log.info("revised → %d items", len(result))
    return result
