"""
Registry of the brands/accounts this pipeline runs for. Each entry holds
whatever each data source needs to identify that account - add a brand
once here, then every script just takes --brand <key>.
"""

BRANDS = {
    "campus": {
        "display_name": "Campus",
        "amazon_entity_id": "ENTITY3MIU8ACVTRQ4D",
        "amazon_region": "in",
        "amazon_country_filter": None,  # single-country entity, no filter needed
        "hector_brand_name": "Campus",
        "hector_country": None,  # fresh Hector sessions default to IN already
        "hector_mcp_tenant": "CampusIN77061c54e1a2c807",
        "currency_symbol": "₹",
        # The pill tabs worked exactly for weeks, then started showing the
        # same "selected but doesn't filter" bug as bbe-us/bbe-ca (confirmed
        # live - reproduced twice in a row). Since the Filters panel's Type
        # checkbox method is proven exact for the other two brands, use it
        # here too rather than trust a mechanism that's shown it can flip
        # from reliable to broken with no code change on our end.
        "amazon_type_filter_method": "search",
        "amazon_currency_search": "Indian Rupee",
        "amazon_currency_option": "Indian Rupee (INR ₹)",
        "amazon_switcher_country": None,  # single-country account, no picker shown
    },
    "bbe-us": {
        "display_name": "Beauty-by-Earth",
        "amazon_entity_id": "ENTITY1PCD7TA33W7WL",
        # Confirmed live (from the user's own account-switcher screenshots):
        # both BBE entities are reached via advertising.amazon.com, the
        # SAME domain/session as each other - NOT separate per-country
        # login domains like Campus's advertising.amazon.in. Sharing the
        # "us" region key here means both reuse one saved login, no
        # second 2FA needed for the Canada entity.
        "amazon_region": "us",
        # This entity spans 8 marketplaces (Canada, France, Germany, Italy,
        # Mexico, Spain, UK, US - confirmed live) under one umbrella -
        # without this filter the scraped totals silently blend all of
        # them together.
        "amazon_country_filter": "United States",
        "hector_brand_name": "Beauty by Earth",
        "hector_country": "US",
        "hector_mcp_tenant": "BeautybyEarthUS458022c35b29da3a1ab7bsd",
        "currency_symbol": "$",
        # Confirmed live: for this account the ad-type pill tabs register as
        # "selected" but never actually filter the grid, silently leaving
        # "All"'s numbers on screen. The "Search with metrics or settings"
        # box's own Type filter does work correctly here (SP+SB+SD summed
        # to All exactly in testing) - Campus doesn't need this, its pill
        # tabs are already exact.
        "amazon_type_filter_method": "search",
        "amazon_currency_search": "United States Dollar",
        "amazon_currency_option": "United States Dollar (USD $)",
        "amazon_switcher_country": "United States",
    },
    "bbe-ca": {
        "display_name": "Beauty by Earth Products",
        "amazon_entity_id": "ENTITY2EAKPBPQ8V6BJ",
        "amazon_region": "us",  # same login/domain as bbe-us - see note there
        "amazon_country_filter": "Canada",
        "hector_brand_name": "Beauty by Earth Products",
        "hector_country": "Canada",
        "hector_mcp_tenant": "BeautybyEarthProductsCA036852c35b29da3a1ab7bsd",
        "currency_symbol": "CA$",
        # Same pill-tab bug as bbe-us (confirmed live, same account family) -
        # see the note on bbe-us's amazon_type_filter_method.
        "amazon_type_filter_method": "search",
        "amazon_currency_search": "Canadian Dollar",
        "amazon_currency_option": "Canadian Dollar (CAD $)",
        "amazon_switcher_country": "Canada",
    },
}


def get_brand(key: str) -> dict:
    if key not in BRANDS:
        raise SystemExit(f"Unknown brand {key!r} - choices are: {', '.join(BRANDS)}")
    return BRANDS[key]
