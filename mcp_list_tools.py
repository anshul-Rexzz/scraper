"""Connect to the Hector Amazon MCP server with our saved token and list
its available tools, so we know what's actually callable."""
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
            tools = await session.list_tools()
            for t in tools.tools:
                print(f"- {t.name}: {t.description[:150] if t.description else ''}")
                print(f"  schema: {t.input_schema}")


if __name__ == "__main__":
    asyncio.run(main())
