"""
Direct login to a specific country's Amazon Ads console domain (not via
mid-session entity switch, which triggers a flaky cross-region SSO
redirect for single-country entities). Uses the AMAZON_ADS_* credentials,
with a separate saved session per country so they don't collide.
"""
import os

from dotenv import load_dotenv

from ads_account import AdsAccount

load_dotenv()


def get_regional_account(country_code: str) -> AdsAccount:
    return AdsAccount(
        "AMAZON_ADS",
        storage_state_path=f"storage_state_{country_code}.json",
        country_code_override=country_code,
    )


def get_account_for_brand(brand_key: str, country_code: str) -> AdsAccount:
    """Like get_regional_account(), but keys the saved session by brand
    instead of region - so two brands sharing one region (e.g. bbe-us and
    bbe-ca both login via advertising.amazon.com) each get their own
    independent browser session instead of silently reusing each other's.

    Picks up brand-specific credentials (AMAZON_ADS_<BRAND>_EMAIL etc.) if
    they're set in .env; otherwise falls back to the shared AMAZON_ADS_*
    login, so this works today even before any brand gets its own
    distinct account."""
    brand_prefix = f"AMAZON_ADS_{brand_key.upper().replace('-', '_')}"
    env_prefix = brand_prefix if f"{brand_prefix}_EMAIL" in os.environ else "AMAZON_ADS"
    return AdsAccount(
        env_prefix,
        storage_state_path=f"storage_state_{brand_key}.json",
        country_code_override=country_code,
    )
