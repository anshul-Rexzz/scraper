"""Test calling targeting_360 for the SP/SB/SD breakdown we need -
omitting tenant first to see the reachable-accounts list if more than
one account is in scope for this login."""
import asyncio
import json

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
            result = await session.call_tool("targeting_360", {
                "shape": "grouped",
                "group_by": ["campaign_type"],
                "fields": ["ad_orders", "ad_revenue"],
                "date_range": {"start_date": "2026-08-31", "end_date": "2026-09-29"},
            })
            for block in result.content:
                text = getattr(block, "text", None)
                if text:
                    try:
                        print(json.dumps(json.loads(text), indent=2)[:4000])
                    except json.JSONDecodeError:
                        print(text[:4000])


if __name__ == "__main__":
    asyncio.run(main())
