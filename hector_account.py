"""
Login/session handling for Hector (app.hectorai.live). No 2FA — just
email + password, so this is much simpler than the Amazon Ads flow.
"""
import os

from dotenv import load_dotenv
from playwright.sync_api import Page

load_dotenv()

EMAIL = os.environ["HECTOR_EMAIL"].strip()
PASSWORD = os.environ["HECTOR_PASSWORD"].strip()
BASE_URL = os.environ.get("HECTOR_BASE_URL", "https://app.hectorai.live")
HEADLESS = os.environ.get("HEADLESS", "true").lower() != "false"

STORAGE_STATE_PATH = "storage_state_hector.json"


def _is_logged_in(page: Page) -> bool:
    return "login" not in page.url.lower()


def _perform_login(page: Page) -> None:
    page.goto(BASE_URL)
    page.wait_for_selector("input[name='email']", timeout=30_000)
    page.fill("input[name='email']", EMAIL)
    page.fill("input[name='password']", PASSWORD)
    page.click("button#submit_btn")
    page.wait_for_load_state("networkidle", timeout=30_000)

    if not _is_logged_in(page):
        raise RuntimeError(
            "Login did not complete as expected. Re-run with HEADLESS=false "
            "to watch it happen."
        )


def get_authenticated_context(playwright):
    # A headed Chromium window launched programmatically (no real user click
    # to focus it) doesn't get OS focus — Windows/Chrome then throttles its
    # background-timer and rendering pipeline, which looks exactly like
    # clicks mysteriously hanging even though simple reads (url/title/
    # screenshot) still work fine. These flags disable that throttling.
    browser = playwright.chromium.launch(
        headless=HEADLESS,
        args=[
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
        ],
    )

    if os.path.exists(STORAGE_STATE_PATH):
        context = browser.new_context(storage_state=STORAGE_STATE_PATH)
        page = context.new_page()
        page.goto(BASE_URL)
        page.wait_for_timeout(2000)
        if _is_logged_in(page):
            # Bug fixed: this used to return without closing this check page,
            # leaving it open as a background tab once callers opened their
            # own via context.new_page() — a backgrounded Chromium tab gets
            # heavily throttled, which looked exactly like clicks mysteriously
            # hanging (url/title/screenshot all still worked fine, since
            # those aren't affected by tab-visibility throttling).
            page.close()
            return browser, context
        page.close()
        context.close()

    context = browser.new_context()
    page = context.new_page()
    _perform_login(page)
    context.storage_state(path=STORAGE_STATE_PATH)
    page.close()
    return browser, context


def switch_brand(page, brand_name: str, country: str | None = None) -> None:
    """Switches the active brand via the top-right account switcher.
    Confirmed live: this admin login covers many unrelated client
    accounts (it defaulted to "3M - Car Care" on fresh login, not any of
    our target brands), and the switcher's search is scoped to whatever
    country is currently selected there - a fresh session always starts
    on "IN" (confirmed live across repeated fresh sessions), so a brand
    in another country (e.g. "Beauty by Earth" under US) won't show up
    until that's switched first via `country` (the dropdown option's own
    text, e.g. "US" or "Canada" - not necessarily a 2-letter ISO code)."""
    # The switcher trigger is whatever brand name is currently showing,
    # which we don't know in advance - "Role:" is the one stable anchor
    # next to it regardless of which brand is active.
    page.locator("text=Role:").first.click(force=True)
    page.wait_for_timeout(1500)

    if country:
        panel = page.locator("text=AMS").first.locator("xpath=ancestor::div[3]")
        panel.get_by_text("IN", exact=True).first.click(force=True)  # opens the country list
        page.wait_for_timeout(1000)
        panel.get_by_text(country, exact=True).first.click(force=True)
        page.wait_for_timeout(1500)

    search_box = page.locator("input[placeholder='Search']").first
    search_box.fill(brand_name)
    page.wait_for_timeout(1500)
    page.locator(f"text={brand_name}").first.click(force=True)
    page.wait_for_timeout(4000)
