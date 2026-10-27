"""
Sets Hector's dashboard date range to a specific day/month/year range.

Root cause of the old cross-month bug (confirmed via live DOM inspection):
the page renders the date range picker as TWO separate, independent
`.rdrCalendarWrapper` widgets side by side (not one widget with 2 months
sharing a nav bar, as originally assumed) - the left one drives the
"Compare to" period, the right one (`.rdrCalendarWrapper` index 1) drives
the actual applied range we want to set. Each wrapper has its OWN
`.rdrNextButton`, but that button lives in `.rdrMonthAndYearWrapper`, a
SIBLING of `.rdrMonth` - not a descendant of it. The old code scoped its
`.rdrNextButton` lookup to `.rdrMonth` itself, so it always found zero
matches and hung forever waiting for an element that was never there.

(The month/year <select> dropdowns each wrapper also exposes looked like a
cleaner alternative to next-button clicking, but they're a visually-hidden
native control behind the custom-styled picker - Playwright's actionability
checks time out on them. Sticking with next-button clicks, scoped correctly
this time.)
"""
from playwright.sync_api import Error as PlaywrightError

MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _advance_months_via_button(wrapper, months_to_advance: int) -> None:
    """Confirmed live: advancing to a SECOND month via the JS-dispatched
    <select> change event (as _navigate_to_month does) silently drops the
    in-progress range selection from the already-clicked start day - the
    resulting "applied range" ends up being just that single start day,
    with no error anywhere. A REAL click on the "next month" button
    preserves that selection correctly, confirmed live. The button only
    goes forward (no "previous" button exists on this page) - fine here
    since this is only ever used to advance from month_start to a later
    month_end, never backward."""
    next_button = wrapper.locator("button.rdrNextButton")
    for _ in range(months_to_advance):
        next_button.first.click(timeout=15000, force=True)
        wrapper.page.wait_for_timeout(800)


def _navigate_to_month(wrapper, target_month: int, target_year: int) -> None:
    """The picker only exposes a "next" button (confirmed live: 0 "prev"
    buttons exist anywhere on the page) and its displayed month persists
    across runs/sessions - so a forward-only click loop can never reach a
    target month earlier than whatever the picker was last left on. The
    month/year <select> dropdowns support any direction directly, but are
    a custom-styled, zero-size native control Playwright's actionability
    checks refuse to click/select_option on - so set .value and dispatch
    a real 'change' event via JS instead, which React's onChange picks up
    exactly as if a user had used the (invisible) native control."""
    label = wrapper.locator(".rdrMonthName")
    wrapper.locator(".rdrMonthPicker select").evaluate(
        "(el, v) => { "
        "const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set; "
        "setter.call(el, v); "
        "el.dispatchEvent(new Event('change', { bubbles: true })); }",
        str(target_month - 1),
    )
    wrapper.page.wait_for_timeout(500)
    wrapper.locator(".rdrYearPicker select").evaluate(
        "(el, v) => { "
        "const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set; "
        "setter.call(el, v); "
        "el.dispatchEvent(new Event('change', { bubbles: true })); }",
        str(target_year),
    )
    wrapper.page.wait_for_timeout(1000)

    target_label = f"{MONTH_NAMES[target_month - 1]} {target_year}"
    actual = label.inner_text(timeout=15000).strip()
    if actual != target_label:
        raise RuntimeError(f"Month/year select landed on '{actual}', expected '{target_label}'")


def set_date_range(
    page,
    base_url: str,
    day_start: int,
    month_start: int,
    year_start: int,
    day_end: int,
    month_end: int,
    year_end: int,
    attempts: int = 5,
) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            page.goto(base_url)
            page.wait_for_selector("p.f-w-600.mr-1", timeout=45000)
            page.wait_for_timeout(8000)

            print("  [1] clicking trigger")
            page.locator("p.f-w-600.mr-1").first.click(timeout=30000, force=True)
            page.wait_for_selector(".rdrCalendarWrapper", timeout=45000)
            page.wait_for_timeout(2500)
            print("  [2] picker open")

            wrappers = page.locator(".rdrCalendarWrapper")
            if wrappers.count() < 2:
                raise RuntimeError(f"expected 2 calendar wrappers, found {wrappers.count()}")
            current = wrappers.nth(1)  # the "Current Date" / applied-range widget

            print(f"  [3] navigating to {MONTH_NAMES[month_start - 1]} {year_start}")
            _navigate_to_month(current, month_start, year_start)

            print(f"  [4] clicking day {day_start}")
            active_days = current.locator("button.rdrDay:not(.rdrDayPassive)")
            active_days.get_by_text(str(day_start), exact=True).click(
                timeout=30000, force=True, no_wait_after=True
            )
            page.wait_for_timeout(1500)
            print("  [5] day_start clicked")

            if (month_end, year_end) != (month_start, year_start):
                months_to_advance = (year_end - year_start) * 12 + (month_end - month_start)
                print(f"  [6] advancing {months_to_advance} month(s) to {MONTH_NAMES[month_end - 1]} {year_end}")
                _advance_months_via_button(current, months_to_advance)
                label = current.locator(".rdrMonthName").inner_text(timeout=15000).strip()
                target_label = f"{MONTH_NAMES[month_end - 1]} {year_end}"
                if label != target_label:
                    raise RuntimeError(f"Advanced to '{label}', expected '{target_label}'")
                active_days = current.locator("button.rdrDay:not(.rdrDayPassive)")

            print(f"  [7] clicking day {day_end}")
            active_days.get_by_text(str(day_end), exact=True).click(
                timeout=30000, force=True, no_wait_after=True
            )
            page.wait_for_timeout(1500)
            print("  [8] day_end clicked, clicking Apply")

            page.locator("text=Apply").first.click(timeout=30000, force=True, no_wait_after=True)
            page.wait_for_timeout(6000)
            print("  [9] Apply clicked")

            print(f"Date range set on attempt {attempt}")
            return True
        except PlaywrightError as e:
            print(f"  attempt {attempt}/{attempts} failed: {e.message.splitlines()[0]}")
            page.screenshot(path=f"hector_date_fail_{attempt}.png", full_page=True)
            if attempt == attempts:
                return False
            page.wait_for_timeout(3000)
    return False
