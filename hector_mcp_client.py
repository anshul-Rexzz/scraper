"""
Standalone client for the Hector Amazon MCP server's targeting_360 tool -
the "Hector MCP" data source for the reconciliation sheet. Uses the
OAuth token from hector_mcp_account.py; no Claude Code involved, so this
runs on any machine with this repo and the saved token file.
"""
import asyncio
import json

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from hector_mcp_account import get_access_token

URL = "https://mcp.hectorai.live/amazon"
TYPE_TO_KEY = {"SP": "sp", "SB": "sb", "SD": "sd"}


async def _fetch(start_date: str, end_date: str, tenant: str | None) -> dict:
    token = get_access_token()
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})
    async with streamable_http_client(URL, http_client=http_client) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            args = {
                "shape": "grouped",
                "group_by": ["campaign_type"],
                "fields": ["ad_orders", "ad_revenue"],
                "date_range": {"start_date": start_date, "end_date": end_date},
            }
            if tenant:
                args["tenant"] = tenant
            result = await session.call_tool("targeting_360", args)
            # The text block carries a human-readable status line followed
            # by the JSON payload on the next line (confirmed live) - skip
            # straight to the first '{'.
            text = next(b.text for b in result.content if getattr(b, "text", None))
            return json.loads(text[text.index("{"):])


def scrape_hector_mcp(date_range: dict) -> dict:
    """Returns {"sp": (orders, revenue), "sb": (...), "sd": (...), "total": (...)}."""
    start_date = f"{date_range['year_start']:04d}-{date_range['month_start']:02d}-{date_range['day_start']:02d}"
    end_date = f"{date_range['year_end']:04d}-{date_range['month_end']:02d}-{date_range['day_end']:02d}"
    tenant = date_range["brand"].get("hector_mcp_tenant")

    payload = asyncio.run(_fetch(start_date, end_date, tenant))

    by_key = {}
    for row in payload["rows"]:
        key = TYPE_TO_KEY[row["campaign_type"]]
        by_key[key] = (row["ad_orders"], row["ad_revenue"])

    summary = payload["summary"]
    if summary.get("ad_orders") is not None and summary.get("ad_revenue") is not None:
        by_key["total"] = (summary["ad_orders"], summary["ad_revenue"])
    else:
        # Some accounts (confirmed live: Beauty by Earth) get summary.
        # ad_orders/ad_revenue = null - the tool's own attribution rule
        # refuses to blend ad types whose attribution windows differ
        # (SP vs SB/SD) into one account-level figure. The per-type rows
        # are still real numbers, so just sum them ourselves.
        orders = sum(v[0] for v in by_key.values())
        revenue = sum(v[1] for v in by_key.values())
        by_key["total"] = (orders, revenue)
    return by_key


if __name__ == "__main__":
    from date_args import parse_date_range
    print(scrape_hector_mcp(parse_date_range("Test Hector MCP call")))
