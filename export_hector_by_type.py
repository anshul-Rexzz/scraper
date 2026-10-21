"""
Derives an SP/SB/SD breakdown (Spend, Ad Revenue, Ad Orders) for Hector by
scraping the Campaign table (711 rows for Campus/Aug — far more tractable
than the Targeting table's 8,000+ rows) and inferring each campaign's type
from its name prefix ("SP | ...", "SB | ...", "SD | ...").

The table loads 50 rows at a time as you scroll (confirmed live) rather
than via classic pagination or a bulk export button, so this scrolls its
last row into view repeatedly until the row count stops growing.

Every step retries a few times before giving up — this app's background
polling makes individual actions flaky, but not actually broken (proven
against the date-range picker, which needed retries but always succeeded
within 5 attempts).
"""
import csv
import os
import re

from playwright.sync_api import sync_playwright

from hector_account import BASE_URL, get_authenticated_context

OUTPUT_DIR = "output"
def classify_campaign_type(name: str) -> str:
    """Campaign names encode type inconsistently across naming conventions
    seen live: leading prefix ("SP | ..."), underscore-delimited infix/suffix
    ("GENTS_Running_Regular_SD"), or a video-brands variant ("SBV | ...").
    Verified against 532 real campaign names: this classifies all but ~1%
    (mostly test/placeholder campaigns with no type info in the name at all)."""
    normalized = name.replace("_", " ").replace("SBKT", "SB KT").replace("SBV", "SB")
    m = re.search(r"\b(SP|SB|SD)\b", normalized, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    if "auto" in name.lower():
        return "SP"  # heuristic: automatic targeting is an SP-only feature
    return "UNKNOWN"


def enable_campaign_types_table(page) -> None:
    """Turns on the "Campaign Types" grouped summary table via the gear
    icon -> Table Display Settings -> Tables -> Targeting -> Campaign
    Types checkbox -> Apply. Confirmed live: this setting does NOT persist
    across fresh sessions (it was on only because of leftover state from
    earlier manual testing) - a fresh login needs this every time."""
    gear = page.locator("[aria-label*='ettings' i]").first
    gear.click(force=True)
    page.wait_for_timeout(1500)

    page.locator("text=Tables").first.click(force=True)
    page.wait_for_timeout(1000)

    modal = page.locator("text=Table Display Settings").first.locator("xpath=ancestor::div[3]")
    modal.locator("text=Targeting").first.click(force=True)
    page.wait_for_timeout(1000)
    modal.locator("text=Campaign Types").first.click(force=True)
    page.wait_for_timeout(500)
    modal.locator("text=Apply").first.click(force=True)
    page.wait_for_timeout(3000)


def find_table_by_header(page, header_text: str, exclude_header: str | None = None):
    """The page renders each section as 3 separate <table>s (pinned-left /
    scrollable / pinned-right columns) — identify the right one by its own
    header content rather than assuming a fixed index, since table order
    isn't stable across runs (confirmed live: it shifted between sessions).

    header_text alone isn't always unique: the Targeting table also has a
    "Campaign Types" COLUMN among its own headers (alongside "Targeting",
    "Match Types", ...), so a plain substring search can match either
    table depending on DOM order that session (confirmed live: this
    silently returned Targeting's ~8,000 keyword rows instead of the
    3-row Campaign Types summary table). exclude_header rules out a
    table that also carries a header unique to the wrong match."""
    tables = page.locator("table")
    for i in range(tables.count()):
        headers = tables.nth(i).locator("thead th").all_inner_texts()
        if any(header_text in h for h in headers):
            if exclude_header and any(exclude_header in h for h in headers):
                continue
            return tables.nth(i)
    raise RuntimeError(f"No table found with header containing '{header_text}'")


def load_all_campaign_rows(page, expected_total: int, max_rounds: int = 40) -> list[dict]:
    page.wait_for_selector("table", timeout=20000)
    table = find_table_by_header(page, "Campaign Name")
    print("Matched table headers:", table.locator("thead th").all_inner_texts())

    scroller = table.locator("xpath=ancestor::div[contains(@class,'scroller')]").first

    def capture_visible_rows(collected: dict) -> None:
        # The list windows/prunes earlier rows once enough accumulate
        # (observed live: DOM count went 750 -> 700 after further scrolling),
        # so rows must be saved as soon as they're visible, not only read
        # once at the very end. Keyed by (name, start date, budget) since
        # campaign names aren't guaranteed unique on their own.
        rows = table.locator("tbody tr")
        for i in range(rows.count()):
            texts = rows.nth(i).locator("td").all_inner_texts()
            if len(texts) > 6 and texts[2].strip():
                key = (texts[2].strip(), texts[4].strip(), texts[6].strip())
                collected[key] = texts

    collected: dict = {}
    prev_count = -1
    stall_rounds = 0
    for round_num in range(max_rounds):
        rows = table.locator("tbody tr")
        count = rows.count()
        capture_visible_rows(collected)
        print(f"  round {round_num}: {count} in DOM, {len(collected)} captured (target {expected_total})")
        if len(collected) >= expected_total:
            break
        if count == prev_count:
            stall_rounds += 1
            if stall_rounds >= 5:  # 5 consecutive no-growth rounds = genuinely done
                break
        else:
            stall_rounds = 0
        prev_count = count
        for attempt in range(6):
            try:
                scroller.evaluate("el => el.scrollTop = el.scrollHeight", timeout=15000)
                break
            except Exception as e:
                print(f"    scroll attempt {attempt + 1}/6 failed: {e}")
                if attempt == 5:
                    raise
                page.wait_for_timeout(3000)
                scroller = table.locator("xpath=ancestor::div[contains(@class,'scroller')]").first
        page.wait_for_timeout(6000)

    return [{"campaign_name": key[0], "cells": texts} for key, texts in collected.items()]


def write_by_type_csv(raw_path: str) -> None:
    import pandas as pd

    df = pd.read_csv(raw_path)
    for col in ["spend", "ad_revenue"]:
        df[col] = df[col].replace(r"[₹$,]", "", regex=True)
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["ad_orders"] = pd.to_numeric(df["ad_orders"].astype(str).str.replace(",", ""), errors="coerce").fillna(0)

    by_type = df.groupby("type").agg(
        campaign_count=("campaign_name", "count"),
        spend=("spend", "sum"),
        ad_revenue=("ad_revenue", "sum"),
        ad_orders=("ad_orders", "sum"),
    )
    path = os.path.join(OUTPUT_DIR, "hector_by_type.csv")
    by_type.to_csv(path)
    print(f"Saved {path}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser, context = get_authenticated_context(p)
        page = context.new_page()
        page.goto(f"{BASE_URL}/amazon/targeting")
        page.wait_for_timeout(8000)

        input(
            "\nIn the browser window that just opened, please manually set the\n"
            "date range to 31 Aug - 29 Sep and click Apply (the automated picker\n"
            "hits a UI bug on this specific cross-month selection).\n"
            "Once you see the new range applied, press Enter here to continue...\n"
        )

        page.wait_for_selector("table", timeout=20000)
        campaign_table = find_table_by_header(page, "Campaign Name")
        total_text = campaign_table.locator("tfoot").inner_text()
        match = re.search(r"Grand Total Count\s*\(\s*([\d,]+)\s*\)", total_text)
        expected_total = int(match.group(1).replace(",", ""))
        print(f"Expected {expected_total} campaigns")

        rows = load_all_campaign_rows(page, expected_total)
        print(f"Collected {len(rows)} rows")

        # Column indices matched against the table's own <thead> order,
        # confirmed live (texts[2]=Campaign Name, texts[4]=Start Date,
        # texts[6]=Budget all checked out against real values):
        # 0 blank, 1 Active, 2 Campaign Name, 3 Status, 4 Start Date,
        # 5 End Date, 6 Budget, 7-9 bid adjustments, 10 Spend,
        # 11 Ad Revenue, 12 Ad Orders.
        raw_path = os.path.join(OUTPUT_DIR, "hector_campaigns_raw.csv")
        with open(raw_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["campaign_name", "type", "spend", "ad_revenue", "ad_orders"])
            for row in rows:
                cells = row["cells"]
                campaign_type = classify_campaign_type(row["campaign_name"])
                writer.writerow([row["campaign_name"], campaign_type, cells[10], cells[11], cells[12]])
        print(f"Saved {raw_path}")

        write_by_type_csv(raw_path)
        browser.close()


if __name__ == "__main__":
    main()
