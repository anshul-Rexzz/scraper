"""
Shared login/session logic for an Amazon Ads console account, parameterized
by an env-var prefix so multiple distinct accounts (e.g. a personal test
account and a work login with agency access to client brands) can each have
their own credentials and saved session without duplicating this code.
"""
import os

import pyotp
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

_COUNTRY_CONSOLE_DOMAINS = {
    "us": "advertising.amazon.com",
    "in": "advertising.amazon.in",
    "uk": "advertising.amazon.co.uk",
    "de": "advertising.amazon.de",
    "ca": "advertising.amazon.ca",
    "au": "advertising.amazon.com.au",
    "jp": "advertising.amazon.co.jp",
}


class AdsAccount:
    def __init__(self, env_prefix: str, storage_state_path: str, country_code_override: str | None = None):
        self.email = os.environ[f"{env_prefix}_EMAIL"].strip()
        self.password = os.environ[f"{env_prefix}_PASSWORD"].strip()
        # Optional: if not set, _perform_login falls back to asking you to type
        # the current code from your authenticator app at the moment it's needed,
        # instead of computing it from a saved secret.
        self.totp_secret = os.environ.get(f"{env_prefix}_TOTP_SECRET", "").replace(" ", "")
        self.base_url = os.environ.get(f"{env_prefix}_BASE_URL", "https://advertising.amazon.com")
        self.country_code = country_code_override or os.environ.get(f"{env_prefix}_COUNTRY_CODE", "us")
        self.console_url = os.environ.get(f"{env_prefix}_CONSOLE_URL") or (
            f"https://{_COUNTRY_CONSOLE_DOMAINS.get(self.country_code, 'advertising.amazon.com')}"
        )
        # The bare console root 404s regardless of login state, so it's useless as a
        # "still logged in?" probe — use a real authenticated page instead.
        self.check_url = f"{self.console_url}/campaign-manager/all-campaigns"
        self.storage_state_path = storage_state_path
        self.headless = os.environ.get("HEADLESS", "true").lower() != "false"

    def _is_logged_in(self, page: Page) -> bool:
        return (
            "ap/signin" not in page.url
            and "/ap/mfa" not in page.url
            and "page-not-found" not in page.url
        )

    def _perform_login(self, page: Page) -> None:
        # The Ads console's country-specific sign-in page embeds a link to the real
        # Amazon ap/signin (OpenID) flow for that marketplace — grab and follow it
        # rather than guessing the marketing site's various "Sign in" buttons.
        page.goto(f"{self.base_url}/sign-in/{self.country_code}")
        page.wait_for_selector("a[href*='ap/signin']", timeout=30_000)
        signin_href = page.locator("a[href*='ap/signin']").first.get_attribute("href")
        page.goto(signin_href)

        page.wait_for_selector("input#ap_email", timeout=30_000)
        page.fill("input#ap_email", self.email)
        page.click("#continue")

        page.wait_for_selector("input#ap_password", timeout=30_000)
        page.fill("input#ap_password", self.password)
        page.click("#signInSubmit")

        try:
            page.wait_for_selector("input#auth-mfa-otpcode", timeout=15_000)
            if self.totp_secret:
                code = pyotp.TOTP(self.totp_secret).now()
                page.fill("input#auth-mfa-otpcode", code)
                if page.locator("input#auth-mfa-remember-device").count():
                    page.check("input#auth-mfa-remember-device")
                page.click("input#auth-signin-button")
            else:
                # No TOTP secret configured, and this runs with no attached
                # terminal to type a code into (confirmed live: input()
                # just hits an immediate EOFError here) - with HEADLESS=
                # false the browser window is actually visible on screen
                # though, so wait for a human to type the code and submit
                # it directly in that window instead.
                print(
                    "Amazon is asking for a 2FA code - type it into the visible "
                    "browser window yourself and submit it. Waiting up to 5 "
                    "minutes for that to happen..."
                )
                if page.locator("input#auth-mfa-remember-device").count():
                    page.check("input#auth-mfa-remember-device")
                page.wait_for_selector("input#auth-mfa-otpcode", state="detached", timeout=300_000)
                # The OTP field going away can mean success OR an extra
                # verification step replaced it - give that a moment to
                # resolve too before the final _is_logged_in check below.
                page.wait_for_timeout(5000)
        except PlaywrightTimeoutError:
            pass  # no OTP prompt this time (e.g. device already trusted)

        # "networkidle" can time out on this heavy app even after a
        # perfectly successful login (confirmed live: background polling
        # keeps the network "busy" indefinitely) - domcontentloaded plus a
        # fixed settle wait is enough, and _is_logged_in below is the real
        # check that matters.
        try:
            page.wait_for_load_state("domcontentloaded", timeout=30_000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(5000)

        if not self._is_logged_in(page):
            raise RuntimeError(
                "Login did not complete as expected. Amazon may have shown a CAPTCHA, "
                "an extra verification step, or changed its page layout. Re-run with "
                "HEADLESS=false to watch it happen."
            )

    def get_authenticated_context(self, playwright):
        browser = playwright.chromium.launch(headless=self.headless)

        if os.path.exists(self.storage_state_path):
            context = browser.new_context(storage_state=self.storage_state_path)
            page = context.new_page()
            # "load" can hang well past 30s on this heavy app (background
            # polling/analytics beacons keep the network "busy" indefinitely)
            # - confirmed live: several back-to-back runs failed here with
            # ERR_INTERNET_DISCONNECTED / plain timeouts despite the actual
            # network being fine. domcontentloaded + a longer timeout is
            # enough since we only need the login-redirect check to resolve.
            page.goto(self.check_url, timeout=60000, wait_until="domcontentloaded")
            if self._is_logged_in(page):
                return browser, context
            page.close()
            context.close()

        context = browser.new_context()
        page = context.new_page()
        self._perform_login(page)
        context.storage_state(path=self.storage_state_path)
        page.close()
        return browser, context
