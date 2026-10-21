"""
Gets real SP/SB/SD Orders + Sales for Amazon Ads for a given brand. Two
type-filter mechanisms are supported per brand.amazon_type_filter_method:

- "pill" (default, e.g. Campus): click the ad-type pill tabs (All /
  Sponsored Products / Sponsored Brands / Display, Video & Audio) and
  read Orders/Sales from the grid's own pinned-bottom total row. These
  are multi-select toggles, not exclusive tabs - clicking "All" first
  resets any leftover selection so each type is read in isolation.

- "search" (e.g. bbe-us, bbe-ca): use the Filters panel's own Type
  checkbox instead. Confirmed live: for these accounts the pill tabs
  register as "selected" but never actually filter the grid, silently
  leaving "All"'s numbers on screen. The "Search with metrics or
  settings" smart-search box was also tried and rejected - it has no
  suggestion to click for a type with no search history, and silently
  tacks on its own "Active status: All but archived" restriction that
  undercounts archived campaigns relative to the "All" baseline.

scrape_amazon() is the reusable entry point (also used by run_pipeline.py);
main() is just a thin CLI wrapper around it for standalone use.
"""
import csv
import os
import re

from playwright.sync_api import sync_playwright

from amazon_date_range import set_table_date_range
from date_args import parse_date_range
from regional_account import get_account_for_brand

OUTPUT_DIR = "output"
TYPES = ["Sponsored Products", "Sponsored Brands", "Sponsored Display"]
TYPE_TO_KEY = {"Sponsored Products": "sp", "Sponsored Brands": "sb", "Sponsored Display": "sd"}
TYPE_TO_TAB_ID = {
    "Sponsored Products": "sponsoredProducts",
    "Sponsored Brands": "sponsoredBrands",
    "Sponsored Display": "videoAudioDisplay",
}


def _parse_number(s: str) -> float:
    return float(re.sub(r"[^\d.-]", "", s) or 0)


def read_total_row(page) -> tuple[str, str]:
    center_viewport = page.locator(".ag-center-cols-viewport").first
    center_viewport.evaluate("el => el.scrollLeft = el.scrollWidth")
    page.wait_for_timeout(1500)
    row = page.locator(".ag-floating-bottom").first
    orders = row.locator('[col-id="orders"]').inner_text(timeout=15000)
    sales = row.locator('[col-id="sales"]').inner_text(timeout=15000)
    return orders, sales


def _remove_filter_chip(page, title_prefix: str) -> None:
    """Removes one filter chip by its title prefix (e.g. "Campaign
    country:") without disturbing any OTHER active chip."""
    chip_button = page.locator(f"button[title^='{title_prefix}']").first
    if chip_button.count():
        remove_btn = chip_button.locator("xpath=following-sibling::button[@aria-label='remove']").first
        if remove_btn.count():
            remove_btn.click(force=True)
            page.wait_for_timeout(1500)


def _remove_type_chip(page) -> None:
    _remove_filter_chip(page, "Type:")


def search_by_type(page, type_name: str) -> None:
    """Alternate type-filter mechanism for accounts where the pill tabs
    don't actually filter (confirmed live: Beauty-by-Earth's pills register
    as "selected" but leave "All"'s data on screen). Uses the same Filters
    panel as apply_country_filter() - confirmed live this is more reliable
    than the "Search with metrics or settings" autocomplete box, which (a)
    has no suggestion to click for a type with no search history (e.g.
    "Sponsored TV", never searched before) and (b) silently tacks on its
    own "Active status: All but archived" restriction, undercounting
    archived campaigns' historical orders that the pill-tab "All" baseline
    does include."""
    filter_btn = page.locator("[data-testid='storm-ui-icon-filter']").first
    filter_btn.click(force=True)
    page.wait_for_timeout(1500)
    page.locator("text=Type").first.click(force=True)
    page.wait_for_timeout(1500)
    page.locator(f"text={type_name}").first.click(force=True)
    page.wait_for_timeout(500)
    page.locator("text=Apply").first.click(force=True)
    page.wait_for_timeout(3000)


def ensure_currency(page, currency_search_term: str, currency_option_text: str, url: str) -> None:
    """The profile's "Currency (Converted)" setting is shared across the
    WHOLE login account, not per-entity (confirmed live: changing it while
    fixing one brand silently flipped what a completely different brand -
    on a different domain, in a different saved session - displayed too).
    So it has to be actively asserted at the start of every run instead of
    assumed to still be whatever the last run (of ANY brand) left it as."""
    trigger = page.locator("header button, header [role='button']").last
    trigger.click(force=True)
    page.wait_for_timeout(1500)
    currency_trigger = page.locator("button[aria-haspopup='listbox']").nth(1)
    current_text = currency_trigger.get_attribute("aria-label") or ""
    if currency_search_term.lower() in current_text.lower():
        page.keyboard.press("Escape")
        return
    currency_trigger.click(force=True)
    page.wait_for_timeout(1500)
    currency_search = page.locator("input[placeholder='Search']").last
    currency_search.fill(currency_search_term)
    page.wait_for_timeout(1500)
    page.locator(f"text={currency_option_text}").first.click(force=True)
    page.wait_for_timeout(1000)
    page.locator("text=Change currency").first.click(force=True)
    page.wait_for_timeout(5000)
    # A fixed wait alone isn't reliable here (confirmed live, repeatedly -
    # the grid can keep serving stale/partial data for a while after a
    # currency change settles visually) - force a clean reload instead of
    # hoping the in-place state has fully caught up.
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)


def apply_country_filter(page, country_name: str, attempts: int = 3) -> None:
    """Some entities span several marketplaces under one umbrella
    (confirmed live: Beauty-by-Earth covers 8 countries) - without this,
    the scraped totals silently blend every country's orders/sales
    together. Applied ONCE and left in place for the whole scrape."""
    for attempt in range(1, attempts + 1):
        try:
            filter_btn = page.locator("[data-testid='storm-ui-icon-filter']").first
            filter_btn.click(force=True)
            page.wait_for_timeout(1500)
            page.locator("text=Campaign country").first.click(force=True)
            page.wait_for_timeout(1500)
            page.locator(f"text={country_name}").first.click(force=True)
            page.wait_for_timeout(500)
            page.locator("text=Apply").first.click(force=True)
            page.wait_for_timeout(3000)
            return
        except Exception as e:
            # Same class of flakiness as the type-filter clicks (confirmed
            # live: the Filters panel occasionally doesn't respond in time)
            # - this one runs just once per scrape, so a hard crash here
            # was wasting an entire run over a one-off UI hiccup.
            if attempt == attempts:
                raise
            print(f"  apply_country_filter: step failed ({e.__class__.__name__}), retrying ({attempt + 1}/{attempts})")
            page.keyboard.press("Escape")
            page.wait_for_timeout(1500)


def switch_amazon_account(page, brand: dict) -> None:
    """Switches to a different brand/entity within the SAME browser
    session via Amazon's own account switcher, instead of opening a
    separate login per brand. Confirmed live: this works reliably even
    ACROSS domains (e.g. advertising.amazon.in -> .com) as long as the
    session's cookies already include a valid login for the destination
    domain - see storage_state_merged.json, built by merging each brand's
    own one-time login rather than letting two SEPARATE logins for the
    SAME domain coexist (confirmed live: merging two independently-
    established sessions for one domain gets the merged session rejected
    entirely - Amazon invalidates the competing cookie)."""
    page.locator("button[data-takt-id='header_account-switcher-trigger']").first.click(force=True)
    page.wait_for_timeout(2000)
    page.locator("input[placeholder='Search accounts']").first.fill(brand["display_name"])
    page.wait_for_timeout(2000)
    page.get_by_text(brand["display_name"], exact=True).first.click(force=True)
    page.wait_for_timeout(4000)
    if "choose-account" in page.url:
        # Confirmed live: the first click above doesn't always stick -
        # this intermediate page can still show the PREVIOUS brand selected,
        # requiring the search+select to be redone here before picking the
        # country (only shown for entities spanning multiple marketplaces).
        page.locator("text=Change account").first.click(force=True)
        page.wait_for_timeout(2000)
        page.locator("input[placeholder='Search accounts']").first.fill(brand["display_name"])
        page.wait_for_timeout(2000)
        page.get_by_text(brand["display_name"], exact=True).first.click(force=True)
        page.wait_for_timeout(1500)
        if brand.get("amazon_switcher_country"):
            try:
                # Confirmed live: this click can register fine while
                # Playwright's own post-click "wait for navigation" check
                # times out anyway - the cross-domain SSO handoff that
                # follows is just slow, not stuck. Don't treat that as a
                # failure; the caller re-checks page.url either way.
                page.get_by_text(brand["amazon_switcher_country"], exact=True).first.click(
                    force=True, timeout=45000
                )
            except Exception:
                pass
        page.wait_for_timeout(8000)


def click_tab(page, tab_id: str, attempts: int = 3) -> None:
    """The "selected" indicator differs by account/markup variant
    (confirmed live): Campus's pill flips its own [aria-selected], while
    Beauty-by-Earth's [aria-selected] never changes at all - its actual
    toggle state lives on the inner <button>'s aria-pressed instead.
    Accept either so this works across both."""
    tab = page.locator(f"#{tab_id}")
    selected_selector = f"#{tab_id}[aria-selected='true'], #{tab_id} button[aria-pressed='true']"
    for attempt in range(1, attempts + 1):
        tab.click(force=True)
        try:
            page.wait_for_selector(selected_selector, timeout=25000)
            break
        except Exception:
            if attempt == attempts:
                raise
            print(f"  retrying click on #{tab_id} (attempt {attempt + 1}/{attempts})")
            page.wait_for_timeout(1000)
    page.wait_for_load_state("networkidle", timeout=30000)


def _scrape_on_page(page, date_range: dict, url: str) -> dict:
    """The actual scraping work, assuming `page` is already authenticated
    and sitting on (or about to navigate to) the right brand's entity -
    shared by both scrape_amazon() (opens its own single-brand session)
    and scrape_amazon_multi() (one shared session, switched between
    brands in-app)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    brand = date_range["brand"]

    if brand.get("amazon_currency_search") and brand.get("amazon_currency_option"):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        ensure_currency(page, brand["amazon_currency_search"], brand["amazon_currency_option"], url)

    if not set_table_date_range(
        page, url,
        date_range["day_start"], date_range["month_start"], date_range["year_start"],
        date_range["day_end"], date_range["month_end"], date_range["year_end"],
    ):
        raise RuntimeError("Could not set the Amazon table date range")

    # Any filter chips persist server-side across sessions (confirmed
    # live), same as the account's last-active tab did - so a fresh
    # run can silently inherit a leftover filter from a prior session
    # unless explicitly cleared first. This also clears any stale
    # Campaign country chip from a previous brand's run before
    # applying this brand's own.
    _remove_filter_chip(page, "Campaign country:")
    _remove_type_chip(page)
    _remove_filter_chip(page, "Active status:")
    # The "Find a campaign" free-text search box is a separate filter
    # from the chips above and persists server-side the same way -
    # confirmed live: a stray search term left over from an earlier
    # session can silently narrow "All" down to near-nothing.
    # The exact placeholder varies by account/markup variant (confirmed
    # live: "Find a campaign" for some, "Search by name or ID" for others)
    # - try both rather than assume one.
    name_search = page.locator(
        "input[placeholder='Find a campaign'], input[placeholder='Search by name or ID']"
    ).first
    if name_search.count() and name_search.input_value():
        name_search.fill("")
        name_search.press("Enter")
        page.wait_for_timeout(3000)
    page.wait_for_timeout(1000)

    if brand.get("amazon_country_filter"):
        apply_country_filter(page, brand["amazon_country_filter"])

    raw_rows = []

    # Reset to "All" first even for the baseline read itself - the
    # account persists whatever tab was last active server-side, so a
    # fresh session can land on a leftover tab from a prior run.
    click_tab(page, "all")
    page.wait_for_timeout(2000)
    all_orders, all_sales = read_total_row(page)
    print(f"All: Orders={all_orders} Sales={all_sales}")
    raw_rows.append({"type": "All", "orders": all_orders, "sales": all_sales})

    by_key = {"total": (_parse_number(all_orders), _parse_number(all_sales))}

    filter_method = brand.get("amazon_type_filter_method", "pill")
    previous_result = (all_orders, all_sales)
    for type_name in TYPES:
        if filter_method == "search":
            for attempt in range(1, 4):
                try:
                    # Confirmed live: a hard timeout can come from EITHER the
                    # Filters-panel click sequence itself OR the total-row
                    # read afterward - both are the same underlying flake
                    # (the UI occasionally doesn't settle in time), so both
                    # need to retry the same way instead of crashing the
                    # whole run.
                    _remove_type_chip(page)
                    search_by_type(page, type_name)
                    orders, sales = read_total_row(page)
                except Exception as e:
                    if attempt == 3:
                        raise
                    print(f"  {type_name}: step failed ({e.__class__.__name__}), retrying ({attempt}/3)")
                    _remove_type_chip(page)
                    continue
                # Confirmed live: this mechanism can also occasionally
                # fail to apply silently, same stale-data symptom as the
                # pill tabs - retry rather than trust a one-off read.
                if (orders, sales) not in ((all_orders, all_sales), previous_result):
                    _remove_type_chip(page)
                    break
                print(f"  {type_name}: got stale data back, retrying ({attempt}/3)")
                _remove_type_chip(page)
        else:
            tab_id = TYPE_TO_TAB_ID[type_name]
            for attempt in range(1, 4):
                try:
                    # Confirmed live: these are multi-select toggles, not
                    # exclusive tabs - reset to "All" first so each type is
                    # read in isolation.
                    click_tab(page, "all")
                    page.wait_for_timeout(1000)
                    click_tab(page, tab_id)
                    page.wait_for_timeout(3000)
                    orders, sales = read_total_row(page)
                except Exception as e:
                    if attempt == 3:
                        raise
                    print(f"  {type_name}: step failed ({e.__class__.__name__}), retrying ({attempt}/3)")
                    continue
                # A type filter that silently fails to apply (confirmed
                # live: happens intermittently) leaves the grid showing
                # EITHER the unfiltered "All" data, OR - a newer failure
                # mode confirmed live - the PREVIOUS type's still-stale
                # data. A single type can never equal the combined total
                # exactly, nor coincidentally equal a different type's
                # total to the cent, so either match means retry.
                if (orders, sales) not in ((all_orders, all_sales), previous_result):
                    break
                print(f"  {type_name}: got stale data back, retrying ({attempt}/3)")
        print(f"{type_name}: Orders={orders} Sales={sales}")
        raw_rows.append({"type": type_name, "orders": orders, "sales": sales})
        by_key[TYPE_TO_KEY[type_name]] = (_parse_number(orders), _parse_number(sales))
        previous_result = (orders, sales)

    path = os.path.join(
        OUTPUT_DIR, f"{date_range['brand_key']}_amazon_by_type_{date_range['label']}.csv"
    )
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["type", "orders", "sales"])
        writer.writeheader()
        writer.writerows(raw_rows)
    print(f"Saved {path}")

    return by_key


def scrape_amazon(date_range: dict) -> dict:
    """Returns {"sp": (orders, sales), "sb": (...), "sd": (...), "total": (...)}.
    Standalone single-brand entry point - opens its own browser session for
    just this one brand. For scraping several brands in one run, use
    scrape_amazon_multi() instead, which shares one session across all of
    them via the in-app account switcher."""
    brand = date_range["brand"]
    if not brand.get("amazon_entity_id"):
        raise RuntimeError(
            f"No Amazon entity id configured for brand {date_range['brand_key']!r} "
            "- add it to brands.py first."
        )
    account = get_account_for_brand(date_range["brand_key"], brand["amazon_region"])
    url = f"{account.console_url}/campaign-manager/all-campaigns?entityId={brand['amazon_entity_id']}"

    with sync_playwright() as p:
        browser, context = account.get_authenticated_context(p)
        page = context.new_page()
        result = _scrape_on_page(page, date_range, url)
        # A reused (not freshly-logged-in) session was never re-saved to
        # disk before (confirmed live - get_authenticated_context() only
        # writes storage_state right after a fresh login). If Amazon
        # silently rotates session cookies during normal use, as most apps
        # do, those updates were being discarded every time, so the file on
        # disk slowly going stale was invisible until it finally failed
        # outright. Saving the post-scrape state here keeps it current.
        context.storage_state(path=account.storage_state_path)
        browser.close()
    return result


def _scrape_amazon_same_region(date_ranges: list[dict]) -> dict[str, dict]:
    """Scrapes several brands that all share the same amazon_region (and
    therefore the same underlying Amazon login - confirmed live for
    bbe-us/bbe-ca) in ONE shared browser session, switching between them
    in-app instead of opening a separate login per brand. Reuses the
    FIRST brand's own saved session directly - no separate "merged" file
    needed, since brands in one region already share one login. Cross-
    region switching is deliberately NOT attempted here (confirmed live,
    repeatedly: Amazon's cross-region SSO handoff is unreliable even with
    valid cookies for the destination domain, unlike same-region switches
    which have been consistently reliable) - scrape_amazon_brands() keeps
    different regions in separate sessions for exactly this reason."""
    first_brand = date_ranges[0]["brand"]
    region = first_brand["amazon_region"]
    account = get_account_for_brand(date_ranges[0]["brand_key"], region)
    headless = os.environ.get("HEADLESS", "true").lower() != "false"
    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=account.storage_state_path)
        page = context.new_page()

        for i, date_range in enumerate(date_ranges):
            brand = date_range["brand"]
            if not brand.get("amazon_entity_id"):
                raise RuntimeError(
                    f"No Amazon entity id configured for brand {date_range['brand_key']!r} "
                    "- add it to brands.py first."
                )
            url = f"{account.console_url}/campaign-manager/all-campaigns?entityId={brand['amazon_entity_id']}"

            print(f"--- Switching to {brand['display_name']} ---")
            if i == 0:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)
            else:
                switch_amazon_account(page, brand)
            if "ap/signin" in page.url or "/ap/mfa" in page.url:
                raise RuntimeError(
                    f"Switching to {brand['display_name']!r} hit a login page instead of "
                    f"a seamless in-app switch - {account.storage_state_path} may have "
                    "expired. Re-run with HEADLESS=false to refresh it."
                )
            # Confirmed live: a bare page.goto() to the plain entityId URL
            # (no switchFromEntity param) right after an in-app switch gets
            # intercepted - the current post-switch page.url (which DOES
            # carry that param) is what actually keeps working from here.
            brand_url = page.url
            for attempt in range(1, 3):
                try:
                    results[date_range["brand_key"]] = _scrape_on_page(page, date_range, brand_url)
                    break
                except Exception as e:
                    # Various individual clicks in the scraping flow (the
                    # Filters panel, currency dropdown, etc.) have each
                    # shown occasional one-off flakiness in testing - rather
                    # than chase every one, retry the whole brand once from
                    # a fresh load of its own page before giving up on it.
                    if attempt == 2:
                        raise
                    print(f"  {brand['display_name']}: scrape failed ({e.__class__.__name__}), retrying whole brand")
                    page.goto(brand_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(5000)

        # Same reasoning as scrape_amazon()'s own save: a reused session is
        # never otherwise re-persisted, so any cookie rotation Amazon does
        # during normal use would quietly be lost between runs.
        context.storage_state(path=account.storage_state_path)
        browser.close()

    return results


def scrape_amazon_brands(date_ranges: list[dict]) -> dict[str, dict]:
    """The one entry point for scraping any number of brands for a run.
    Groups them by amazon_region - brands sharing a region run in ONE
    shared, switched session (see _scrape_amazon_same_region); brands in
    different regions each get their own separate session, since cross-
    region switching isn't reliable enough to trust (see that function's
    docstring). This is also why adding a new brand needs no pipeline
    changes: it's one new entry in brands.py, and this function places it
    into the right session automatically based on its amazon_region."""
    by_region: dict[str, list[dict]] = {}
    for date_range in date_ranges:
        region = date_range["brand"]["amazon_region"]
        by_region.setdefault(region, []).append(date_range)

    results = {}
    for region, group in by_region.items():
        print(f"=== Amazon region {region!r}: {[d['brand_key'] for d in group]} ===")
        if len(group) == 1:
            results[group[0]["brand_key"]] = scrape_amazon(group[0])
        else:
            results.update(_scrape_amazon_same_region(group))
    return results


def main():
    date_range = parse_date_range("Amazon Campus SP/SB/SD breakdown for a given date range")
    scrape_amazon(date_range)


if __name__ == "__main__":
    main()
