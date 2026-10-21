"""
Sets an Amazon Ads date-range picker to a specific day/month/year range.
Retries a few times with a fresh page load before giving up, matching the
resilience pattern that worked for Hector's picker.

Two independent pickers exist on the campaign-manager page (confirmed
live): the campaign TABLE's own date filter, and a separate "Date range"
control in the top summary bar that actually drives the Performance/KPI
cards (Impressions, Clicks, Purchases, Sales) - setting one does NOT
update the other. Both pickers share the same calendar widget otherwise
(two adjacent month tables, a single shared "previous"/"next month"
button pair that shifts both calendars together, Apply/Cancel), so one
function drives both via a pluggable `open_picker` step.

Earlier this used a fixed `months_back` relative to "today" to reach the
target month, which broke silently the moment today's real-world date
rolled into a new month (1 month back from October is September, not
August). Now it reads the calendar's own displayed month/year and clicks
forward/backward exactly as many times as needed - correct regardless of
when the script happens to run.
"""
import re
from datetime import date

from playwright.sync_api import Error as PlaywrightError

TABLE_DATE_BUTTON = "[id='campaignOverviewAllCampaigns:dateRangeFilter:openContainer']"
MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_MONTH_YEAR_RE = re.compile(
    r"(" + "|".join(MONTH_NAMES) + r")\D{0,10}(\d{4})"
)


def _read_left_month_year(left_calendar) -> tuple[int, int]:
    container = left_calendar.locator("xpath=..")
    text = container.inner_text(timeout=15000)
    m = _MONTH_YEAR_RE.search(text)
    if not m:
        raise RuntimeError(f"Could not read calendar month/year from: {text[:200]!r}")
    return MONTH_NAMES.index(m.group(1)) + 1, int(m.group(2))


def _navigate_calendar(page, left_calendar, target_month: int, target_year: int) -> None:
    for _ in range(36):
        month, year = _read_left_month_year(left_calendar)
        delta = (target_year - year) * 12 + (target_month - month)
        if delta == 0:
            return
        # delta = (target - current) in months: negative means target is
        # EARLIER than what's showing, which means we need to go backward.
        label = "go to previous month" if delta < 0 else "go to next month"
        page.click(f"button[aria-label='{label}']", timeout=10000, no_wait_after=True)
        page.wait_for_timeout(500)
    raise RuntimeError(f"Could not navigate calendar to {target_month}/{target_year}")


def _set_range_in_open_picker(
    page, day_start: int, month_start: int, year_start: int,
    day_end: int, month_end: int, year_end: int,
) -> None:
    page.wait_for_selector("button[aria-label='go to previous month']", timeout=15000)

    left_calendar = page.locator("table").nth(0)
    right_calendar = page.locator("table").nth(1)
    _navigate_calendar(page, left_calendar, month_start, year_start)

    end_in_next_month = (month_end, year_end) != (month_start, year_start)
    end_calendar = right_calendar if end_in_next_month else left_calendar

    left_calendar.locator("button").get_by_text(str(day_start), exact=True).click(
        timeout=10000, no_wait_after=True
    )
    page.wait_for_timeout(500)
    end_calendar.locator("button").get_by_text(str(day_end), exact=True).click(
        timeout=10000, no_wait_after=True
    )
    page.wait_for_timeout(500)

    page.click("text=Apply", timeout=10000, no_wait_after=True)
    page.wait_for_timeout(4000)


def set_table_date_range(
    page, url: str,
    day_start: int, month_start: int, year_start: int,
    day_end: int, month_end: int, year_end: int,
    attempts: int = 5,
) -> bool:
    """Sets the campaign TABLE's own date filter (bottom section)."""
    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_selector(TABLE_DATE_BUTTON, timeout=30000)
            page.wait_for_timeout(3000)
            page.click(TABLE_DATE_BUTTON, timeout=15000, no_wait_after=True)
            _set_range_in_open_picker(
                page, day_start, month_start, year_start, day_end, month_end, year_end
            )
            print(f"Amazon table date range set on attempt {attempt}")
            return True
        except PlaywrightError as e:
            print(f"  attempt {attempt}/{attempts} failed: {e.message.splitlines()[0]}")
            if attempt == attempts:
                return False
            page.wait_for_timeout(2000)
    return False


def set_date_range(
    page, url: str,
    day_start: int, day_end: int,
    months_back: int = 1, end_in_next_month: bool = False,
    attempts: int = 5,
) -> bool:
    """Backward-compatible wrapper kept for export_account.py's original
    full-export pipeline, which still uses the old months-back-from-today
    style. Carries the same "relative to today" fragility the by-type
    scripts moved away from - fine for that script's own usage pattern,
    just don't reuse this signature for anything new."""
    today = date.today()
    start_month_idx = today.month - 1 - months_back  # 0-based, can go negative
    start_year = today.year + start_month_idx // 12
    start_month = start_month_idx % 12 + 1
    if end_in_next_month:
        end_month_idx = start_month_idx + 1
        end_year = today.year + end_month_idx // 12
        end_month = end_month_idx % 12 + 1
    else:
        end_month, end_year = start_month, start_year
    return set_table_date_range(
        page, url, day_start, start_month, start_year, day_end, end_month, end_year, attempts
    )


def set_kpi_date_range(
    page, url: str,
    day_start: int, month_start: int, year_start: int,
    day_end: int, month_end: int, year_end: int,
    attempts: int = 5,
) -> bool:
    """Sets the top summary bar's OWN date-range control, which is what
    actually drives the Performance/KPI cards (Orders/Sales etc.) -
    confirmed live: this is independent of the campaign table's filter."""
    date_div_pattern = re.compile(r"^\w+ \d+ - \w+ \d+, \d{4}$")
    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_selector("text=Date range", timeout=45000)
            page.wait_for_timeout(3000)
            date_div = page.locator("div").filter(has_text=date_div_pattern).first
            date_div.click(timeout=15000, force=True)
            _set_range_in_open_picker(
                page, day_start, month_start, year_start, day_end, month_end, year_end
            )
            print(f"Amazon KPI date range set on attempt {attempt}")
            return True
        except PlaywrightError as e:
            print(f"  attempt {attempt}/{attempts} failed: {e.message.splitlines()[0]}")
            if attempt == attempts:
                return False
            page.wait_for_timeout(2000)
    return False
