import json
import structlog
import os
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import config

log = structlog.get_logger()


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
        log.info("mcp client connected to server")

    async def stop(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self.session = None

    async def categories(self) -> list[str]:
        res = await self.session.read_resource("categories://list")
        data = json.loads(res.contents[0].text)
        log.info("mcp read resource categories://list → %d", len(data))
        return [c["name"] for c in data]

    async def save_expenses(self, user_id: int, items: list[dict]) -> dict:
        log.info("mcp call_tool save_expenses: user=%s items=%d", user_id, len(items))
        out = await self.session.call_tool(
            "save_expenses", {"user_id": user_id, "items": items}
        )
        result = json.loads(out.content[0].text)
        log.info("mcp save_expenses → %s", result)
        return result

    async def __aenter__(self) -> "MCPClient":
        await self.start()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.stop()
