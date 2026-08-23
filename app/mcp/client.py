from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import config


class MCPClient:
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(config.db_path)
        self._stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None

    async def start(self) -> None:
        params = StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "app.mcp.server"],
            env={**os.environ, "DB_PATH": self._db_path},
        )
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(
            ClientSession(read, write)
        )
        await self.session.initialize()

    async def stop(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self.session = None

    async def categories(self) -> list[str]:
        res = await self.session.read_resource("categories://list")
        data = json.loads(res.contents[0].text)
        return [c["name"] for c in data]

    async def save_expenses(self, user_id: int, items: list[dict]) -> dict:
        out = await self.session.call_tool(
            "save_expenses", {"user_id": user_id, "items": items}
        )
        return json.loads(out.content[0].text)

    async def __aenter__(self) -> "MCPClient":
        await self.start()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.stop()
