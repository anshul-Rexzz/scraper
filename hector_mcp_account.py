"""
Standalone OAuth2+PKCE client for the Hector Amazon MCP server
(https://mcp.hectorai.live/amazon) - no Claude Code involved, so this
works as a plain Python dependency on any machine the pipeline runs on.

One-time interactive step (run `python hector_mcp_account.py` directly):
opens a browser for you to log into Hector, then saves an access+refresh
token pair to hector_mcp_token.json (git-ignored, like the Playwright
storage_state_*.json session files). Every later call just refreshes the
access token silently using the saved refresh_token - no browser, no
login, portable to another machine by copying that one JSON file.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser

import httpx

BASE = "https://mcp.hectorai.live/amazon"
TOKEN_PATH = "hector_mcp_token.json"
REDIRECT_PORT = 53682
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPES = "openid profile amazon_ads"


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _register_client() -> dict:
    resp = httpx.post(
        f"{BASE}/register",
        json={
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_name": "amazon-scrape-pipeline",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _catch_redirect() -> dict:
    """Runs a one-shot local HTTP server to catch the OAuth redirect."""
    result = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            result.update({k: v[0] for k, v in params.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Login complete - you can close this tab.</body></html>")
            done.set()

        def log_message(self, *args):
            pass  # silence default request logging

    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    done.wait(timeout=300)
    server.server_close()
    return result


def _interactive_login() -> dict:
    client = _register_client()
    client_id = client["client_id"]

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    auth_url = f"{BASE}/authorize?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })

    print(f"\nOpening your browser to log into Hector...\nIf it doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    result = _catch_redirect()
    if result.get("state") != state:
        raise RuntimeError("OAuth state mismatch - possible interference, try again.")
    if "code" not in result:
        raise RuntimeError(f"No authorization code returned: {result}")

    token_resp = httpx.post(
        f"{BASE}/token",
        data={
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    token_resp.raise_for_status()
    tokens = token_resp.json()
    tokens["client_id"] = client_id
    tokens["obtained_at"] = time.time()
    return tokens


def _refresh(tokens: dict) -> dict:
    resp = httpx.post(
        f"{BASE}/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    new_tokens = resp.json()
    new_tokens.setdefault("refresh_token", tokens["refresh_token"])  # some servers omit it on refresh
    new_tokens["client_id"] = tokens["client_id"]
    new_tokens["obtained_at"] = time.time()
    return new_tokens


def get_access_token() -> str:
    """The one function everything else needs: a valid Bearer token,
    refreshing or doing the interactive login as needed."""
    tokens = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, encoding="utf-8") as f:
            tokens = json.load(f)
        expires_at = tokens["obtained_at"] + tokens.get("expires_in", 3600)
        if time.time() < expires_at - 60:
            return tokens["access_token"]
        try:
            tokens = _refresh(tokens)
        except httpx.HTTPStatusError:
            tokens = None  # refresh token itself expired/revoked - fall back to login

    if tokens is None:
        tokens = _interactive_login()

    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    return tokens["access_token"]


if __name__ == "__main__":
    token = get_access_token()
    print(f"Access token acquired and saved to {TOKEN_PATH}")
