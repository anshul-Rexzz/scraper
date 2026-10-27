"""
Simplified Hector SP/SB/SD breakdown: reads the "Campaign Types" table
directly (confirmed live: a native grouping Hector's own UI provides -
rows for Sponsored Products/Display/Brands plus a Grand Total, each with
Spend/Ad Revenue/Ad Orders already aggregated) instead of toggling the
Campaign Types FILTER three times and re-reading the Campaign Name
table's Grand Total each time. One page read instead of three.
"""
import csv
import os
import re

from playwright.sync_api import sync_playwright

from hector_account import BASE_URL, STORAGE_STATE_PATH, get_authenticated_context, switch_brand
from hector_date_range import set_date_range
from date_args import parse_date_range
from export_hector_by_type import enable_campaign_types_table, find_table_by_header

OUTPUT_DIR = "output"
_NUMBER_RE = re.compile(r"[^\d.-]")
MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}
TYPE_TO_KEY = {
    "Sponsored Products": "sp", "Sponsored Brands": "sb", "Sponsored Display": "sd",
    "Grand Total": "total",
}


def parse_row(cells: list[str]) -> dict:
    def clean_money(s: str) -> float:
        # Hector shows "---" (not "0") for a type with zero activity in
        # the range (confirmed live) - the regex below keeps "-" as a
        # valid numeric character, so this must be caught explicitly or
        # float() chokes on a string that's nothing but dashes.
        cleaned = _NUMBER_RE.sub("", s)
        return float(cleaned) if any(c.isdigit() for c in cleaned) else 0.0

    def clean_int(s: str) -> int:
        cleaned = re.sub(r"[^\d-]", "", s)
        return int(cleaned) if any(c.isdigit() for c in cleaned) else 0

    # Column order confirmed live: [checkbox, Campaign Types label, Spend,
    # Ad Revenue, Ad Orders, Impression, Clicks, Ad ROAS, ...]
    return {
        "type": cells[1].strip(),
        "spend": clean_money(cells[2]),
        "ad_revenue": clean_money(cells[3]),
        "ad_orders": clean_int(cells[4]),
    }


def scrape_hector(date_range: dict) -> dict:
    """Returns {"sp": (orders, revenue), "sb": (...), "sd": (...), "total": (...)}."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    brand = date_range["brand"]
    with sync_playwright() as p:
        browser, context = get_authenticated_context(p)
        page = context.new_page()

        targeting_url = f"{BASE_URL}/amazon/targeting"
        page.goto(targeting_url)
        page.wait_for_timeout(8000)
        switch_brand(page, brand["hector_brand_name"], brand.get("hector_country"))

        # Confirmed live: set_date_range() can report success (no exception,
        # every click landed) while the page's own generally-flaky date
        # widget silently applied something else entirely - once, a single
        # day instead of the requested 30-day range, with no error at any
        # layer. That got written straight to the sheet as if it were
        # correct. Verifying what the page itself says was applied turns
        # that silent data-corruption bug into a loud, retriable failure.
        expected_start = f"{date_range['day_start']:02d} {MONTH_ABBR[date_range['month_start']]}"
        expected_end = f"{date_range['day_end']:02d} {MONTH_ABBR[date_range['month_end']]}"
        for attempt in range(1, 4):
            if not set_date_range(
                page, targeting_url,
                date_range["day_start"], date_range["month_start"], date_range["year_start"],
                date_range["day_end"], date_range["month_end"], date_range["year_end"],
            ):
                raise RuntimeError("Could not set the Hector date range")

            page.wait_for_timeout(3000)
            body_text = page.locator("body").inner_text()
            idx = body_text.find("Last 30 Days")
            idx = idx if idx >= 0 else body_text.find(":")
            applied_range_text = body_text[idx:idx + 60] if idx >= 0 else "<not found>"
            print("Applied range on page:", applied_range_text)

            if expected_start in applied_range_text and expected_end in applied_range_text:
                break
            print(f"  Applied range doesn't match requested range, retrying ({attempt}/3)")
            if attempt == 3:
                raise RuntimeError(
                    f"Hector's date picker kept applying a different range than requested - "
                    f"expected start {expected_start!r} and end {expected_end!r} somewhere in "
                    f"the page text, got {applied_range_text!r} on every attempt. Refusing to "
                    "scrape with a mismatched range."
                )

        try:
            table = find_table_by_header(page, "Campaign Types", exclude_header="Match Types")
        except RuntimeError:
            # The Campaign Types grouped table is a toggle in Table Display
            # Settings that does NOT persist across fresh sessions
            # (confirmed live) - try turning it on, then look again.
            print("  Campaign Types table not found - enabling it via Table Display Settings...")
            enable_campaign_types_table(page)
            try:
                table = find_table_by_header(page, "Campaign Types", exclude_header="Match Types")
            except RuntimeError:
                all_tables = page.locator("table")
                for i in range(all_tables.count()):
                    headers = all_tables.nth(i).locator("thead th").all_inner_texts()
                    print(f"  table[{i}] headers: {headers}")
                raise
        rows = table.locator("tbody tr")
        results = []
        for i in range(rows.count()):
            cells = rows.nth(i).locator("td").all_inner_texts()
            if len(cells) > 4 and cells[1].strip():
                results.append(parse_row(cells))

        tfoot_text = table.locator("tfoot").inner_text()
        lines = [line.strip() for line in tfoot_text.split("\n") if line.strip()]
        values = lines[1:]

        def _clean_money(s: str) -> float:
            cleaned = _NUMBER_RE.sub("", s)
            return float(cleaned) if any(c.isdigit() for c in cleaned) else 0.0

        def _clean_int(s: str) -> int:
            cleaned = re.sub(r"[^\d-]", "", s)
            return int(cleaned) if any(c.isdigit() for c in cleaned) else 0

        total = {
            "type": "Grand Total",
            "spend": _clean_money(values[0]),
            "ad_revenue": _clean_money(values[1]),
            "ad_orders": _clean_int(values[2]),
        }
        results.append(total)

        for r in results:
            print(r)

        path = os.path.join(
            OUTPUT_DIR, f"{date_range['brand_key']}_hector_by_type_{date_range['label']}.csv"
        )
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["type", "spend", "ad_revenue", "ad_orders"])
            writer.writeheader()
            writer.writerows(results)
        print(f"Saved {path}")

        # Same fix as the Amazon side: a reused session was never re-saved
        # to disk, only a freshly-logged-in one - so any cookie rotation
        # Hector does silently during normal use was getting discarded
        # every run instead of extending the saved session's actual life.
        context.storage_state(path=STORAGE_STATE_PATH)
        browser.close()

    unexpected = [r["type"] for r in results if r["type"] not in TYPE_TO_KEY]
    if unexpected:
        raise RuntimeError(
            f"Got unexpected row types from the Campaign Types table: {unexpected} - "
            "this usually means find_table_by_header matched the wrong table "
            "(e.g. Targeting's search-term rows instead of the 3-row summary)."
        )
    return {TYPE_TO_KEY[r["type"]]: (r["ad_orders"], r["ad_revenue"]) for r in results}


def main():
    date_range = parse_date_range("Hector Campus SP/SB/SD breakdown for a given date range")
    scrape_hector(date_range)


if __name__ == "__main__":
    main()
