"""
Shared CLI date-range (+ brand) parsing so every export script takes the
same --start/--end/--brand flags instead of hardcoded module constants
that had to be hand-edited in multiple files for every new date range or
account.

Usage: python export_amazon_by_type.py --start 31-08-2026 --end 29-09-2026 --brand bbe-us
"""
import argparse
from datetime import datetime

from brands import BRANDS, get_brand


def parse_date_range(description: str):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--start", required=True, help="DD-MM-YYYY, e.g. 31-08-2026")
    parser.add_argument("--end", required=True, help="DD-MM-YYYY, e.g. 29-09-2026")
    parser.add_argument(
        "--brand", default="campus", choices=list(BRANDS),
        help="Which account to pull data for (default: campus)",
    )
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%d-%m-%Y")
    end = datetime.strptime(args.end, "%d-%m-%Y")
    if end < start:
        raise SystemExit(f"--end ({args.end}) is before --start ({args.start})")

    label = f"{start.strftime('%Y-%m-%d')}_to_{end.strftime('%Y-%m-%d')}"
    return {
        "day_start": start.day, "month_start": start.month, "year_start": start.year,
        "day_end": end.day, "month_end": end.month, "year_end": end.year,
        "label": label,
        "brand": get_brand(args.brand),
        "brand_key": args.brand,
    }


def parse_date_range_multi(description: str) -> list[dict]:
    """Like parse_date_range(), but takes any number of brands and returns
    one date_range dict per brand instead of one overall dict - adding a
    brand to brands.py is enough to have it show up here with no further
    changes. --brands is a comma-separated list (default: every brand);
    --brand (singular, kept for scripts/scheduled tasks already calling
    with it) selects just one and takes precedence if both are given."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--start", required=True, help="DD-MM-YYYY, e.g. 31-08-2026")
    parser.add_argument("--end", required=True, help="DD-MM-YYYY, e.g. 29-09-2026")
    parser.add_argument("--brand", choices=list(BRANDS), help="Single account (back-compat with --brand)")
    parser.add_argument(
        "--brands", default=",".join(BRANDS),
        help=f"Comma-separated accounts to pull data for (default: all - {', '.join(BRANDS)})",
    )
    parser.add_argument(
        "--skip-amazon", action="store_true",
        help="Skip the Amazon scrape entirely (e.g. while its login needs a human for 2FA) - "
        "writes Hector-only rows, leaving Amazon Console and Variation %% blank for a later run to fill in.",
    )
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%d-%m-%Y")
    end = datetime.strptime(args.end, "%d-%m-%Y")
    if end < start:
        raise SystemExit(f"--end ({args.end}) is before --start ({args.start})")

    label = f"{start.strftime('%Y-%m-%d')}_to_{end.strftime('%Y-%m-%d')}"
    brand_keys = [args.brand] if args.brand else [b.strip() for b in args.brands.split(",") if b.strip()]
    return [
        {
            "day_start": start.day, "month_start": start.month, "year_start": start.year,
            "day_end": end.day, "month_end": end.month, "year_end": end.year,
            "label": label,
            "brand": get_brand(brand_key),
            "brand_key": brand_key,
            "skip_amazon": args.skip_amazon,
        }
        for brand_key in brand_keys
    ]
