import asyncio
import logging
from typing import Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.llm import extract

log = logging.getLogger(__name__)


class State(TypedDict, total=False):
    user_id: int
    source: str
    text: str
    image: str | None
    categories: list[str]
    default_currency: str
    now: str
    today: str
    items: list[dict]
    meta: dict
    correction: str
    status: str
    result: dict


def build_graph(mcp):
    async def parse_node(state: State):
        log.info("node parse: source=%s", state["source"])
        if state["source"] == "edit":
            return {"items": state["items"], "meta": {}}
        r = await asyncio.to_thread(
            extract.parse,
            state["source"],
            state.get("text", ""),
            state.get("image"),
            state["categories"],
            state["default_currency"],
            state["now"],
            state["today"],
        )
        log.info("node parse → %d items", len(r["items"]))
        return {"items": r["items"], "meta": r["meta"]}

    async def review_node(
        state: State,
    ) -> Command[Literal["persist", "revise", "__end__"]]:
        log.info("node review: interrupt with %d items", len(state["items"]))
        resp = interrupt(
            {
                "items": state["items"],
                "meta": state.get("meta", {}),
                "source": state["source"],
            }
        )
        action = resp.get("action")
        log.info("node review: resumed action=%s", action)
        if action == "approve":
            return Command(goto="persist")
        if action == "revise":
            return Command(goto="revise", update={"correction": resp["correction"]})
        return Command(goto=END, update={"status": "cancelled"})

    async def revise_node(state: State):
        log.info("node revise")
        items = await asyncio.to_thread(
            extract.revise, state["items"], state["correction"], state["categories"]
        )
        return {"items": items}

    async def persist_node(state: State):
        log.info("node persist: saving %d items", len(state["items"]))
        res = await mcp.save_expenses(state["user_id"], state["items"])
        log.info("node persist → %s", res)
        return {"status": "saved", "result": res}

    b = StateGraph(State)
    b.add_node("parse", parse_node)
    b.add_node("review", review_node)
    b.add_node("revise", revise_node)
    b.add_node("persist", persist_node)
    b.add_edge(START, "parse")
    b.add_edge("parse", "review")
    b.add_edge("revise", "review")
    b.add_edge("persist", END)
    return b


def build_agent(mcp, checkpointer=None):
    return build_graph(mcp).compile(checkpointer=checkpointer or MemorySaver())
