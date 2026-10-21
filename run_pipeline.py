"""
Single entry point for the whole reconciliation pipeline: scrape Amazon,
scrape Hector, write both into the Google Sheet - for any number of
brands in one run.

Adding a new brand needs no changes here - just add it to brands.py and
it's automatically included (or pass --brand/--brands to pick specific
ones). Brands sharing an Amazon region run in one shared, switched
browser session; brands in different regions each get their own, since
cross-region switching isn't reliable enough to trust (see
export_amazon_by_type.py's scrape_amazon_brands() docstring).

Usage:
    .venv\\Scripts\\python.exe run_pipeline.py --start 31-08-2026 --end 29-09-2026
    .venv\\Scripts\\python.exe run_pipeline.py --start 31-08-2026 --end 29-09-2026 --brand bbe-us
    .venv\\Scripts\\python.exe run_pipeline.py --start 31-08-2026 --end 29-09-2026 --brands bbe-us,bbe-ca
"""
from date_args import parse_date_range_multi
from export_amazon_by_type import scrape_amazon_brands
from export_hector_by_type_v2 import scrape_hector
from hector_mcp_client import scrape_hector_mcp
from sheets_account import get_worksheet, SHEET_URL
from sheets_write import find_next_empty_row, write_campus_block


def main():
    date_ranges = parse_date_range_multi("Full reconciliation pipeline: Amazon + Hector + Hector MCP + Google Sheet")
    brand_keys = [d["brand_key"] for d in date_ranges]
    label = date_ranges[0]["label"]

    print(f"\n=== Scraping Amazon ({label}): {brand_keys} ===")
    amazon_results = scrape_amazon_brands(date_ranges)

    ws = get_worksheet()

    for date_range in date_ranges:
        brand_key = date_range["brand_key"]
        brand = date_range["brand"]
        amazon = amazon_results[brand_key]

        print(f"\n=== Scraping Hector ({brand_key}) ===")
        hector = scrape_hector(date_range)

        print(f"\n=== Querying Hector MCP ({brand_key}) ===")
        hector_mcp = None
        for attempt in range(1, 4):
            try:
                hector_mcp = scrape_hector_mcp(date_range)
                print(hector_mcp)
                break
            except Exception as e:
                # Confirmed live: this call occasionally hits a transient
                # network/server hiccup (re-running it standalone right after
                # succeeded immediately) - retry a couple of times before
                # giving up and leaving the row blank.
                print(f"  attempt {attempt}/3 failed: {e!r}")
                if attempt == 3:
                    print("Hector MCP call failed after 3 attempts, leaving that row blank.")

        print(f"\n=== Writing {brand_key} to Google Sheet ===")
        row = find_next_empty_row(ws)
        from_date = f"{date_range['day_start']:02d} {_month_name(date_range['month_start'])} {date_range['year_start']}"
        to_date = f"{date_range['day_end']:02d} {_month_name(date_range['month_end'])} {date_range['year_end']}"

        write_campus_block(
            ws, row, from_date=from_date, to_date=to_date, amazon=amazon, hector=hector, hector_mcp=hector_mcp,
            brand_display_name=brand["display_name"],
            currency_symbol=brand["currency_symbol"],
        )
        print(f"Written at row {row}. Sheet: {SHEET_URL}")


def _month_name(month: int) -> str:
    return [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ][month - 1]


if __name__ == "__main__":
    main()
