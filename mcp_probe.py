"""List reachable Hector MCP tenants with this login."""
import asyncio

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from hector_mcp_account import get_access_token

URL = "https://mcp.hectorai.live/amazon"


async def main():
    token = get_access_token()
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})
    async with streamable_http_client(URL, http_client=http_client) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("targeting_360_tenants", {})
            for block in result.content:
                text = getattr(block, "text", None)
                if text:
                    print(text[:6000])


if __name__ == "__main__":
    asyncio.run(main())
