"""Login + receipt-fetching client for the oselya.com.ua resident cabinet.

Auth is a plain Yii2 form login (CSRF token scraped from the login page,
POSTed alongside credentials); the session cookie is all that's needed
afterwards. Fetching a receipt for account X, period M.Y is a two-step dance:
visit /cabinet/info-<account_id>-receipts once (this sets "current object" in
the session), then GET /cabinet/account/get-receipt?date=MM.YYYY - a month
with no issued receipt comes back as an empty text/html body (not an error).
"""
import re
from pathlib import Path

import requests

BASE_URL = "https://oselya.com.ua"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

CREDS = Path.home() / ".oselya_cabinet"


class LoginError(RuntimeError):
    pass


class OselyaClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._current_account = None

    def login(self) -> None:
        r = self.session.get(f"{BASE_URL}/cabinet", timeout=20)
        m = re.search(r'name="_csrf-frontend" value="([^"]+)"', r.text)
        if not m:
            raise LoginError("csrf token not found on login page")
        csrf = m.group(1)
        r = self.session.post(f"{BASE_URL}/login", data={
            "_csrf-frontend": csrf,
            "LoginForm[username]": self.email,
            "LoginForm[password]": self.password,
            "LoginForm[rememberMe]": "0",
        }, timeout=20)
        if "/logout" not in r.text:
            raise LoginError("login failed - check ~/.oselya_cabinet credentials")

    def _select_account(self, account_id: str) -> None:
        # Re-selecting is cheap and avoids relying on it staying sticky across calls.
        if self._current_account == account_id:
            return
        r = self.session.get(f"{BASE_URL}/cabinet/info-{account_id}-receipts", timeout=20)
        r.raise_for_status()
        self._current_account = account_id

    def fetch_receipt(self, account_id: str, month: int, year: int) -> bytes | None:
        """Return the receipt PDF bytes for account_id/month/year, or None if not issued."""
        self._select_account(account_id)
        r = self.session.get(f"{BASE_URL}/cabinet/account/get-receipt",
                              params={"date": f"{month:02d}.{year}"}, timeout=30)
        r.raise_for_status()
        if not r.content or not r.content.startswith(b"%PDF"):
            return None
        return r.content


def load_config() -> dict:
    import json
    return json.loads(CREDS.read_text())
