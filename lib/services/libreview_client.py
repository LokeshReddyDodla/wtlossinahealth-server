import asyncio
import time
from typing import Dict, Optional, Tuple

import httpx
from decouple import config
from loguru import logger
from twocaptcha import TwoCaptcha

from lib.core.cache_store import CacheStore


class LibreViewClient:
    """Async client for interacting with LibreView API."""

    DEFAULT_TIMEOUT = 30.0
    DEFAULT_BASE_URL = "https://api-ap.libreview.io"

    AUTH_TOKEN_KEY = "auth:token"
    AUTH_LOCK_KEY = "auth:lock"

    LOCK_TTL = 15  # seconds
    TOKEN_SAFETY_MARGIN = 30  # seconds

    def __init__(self):
        self.account_id = config("LIBREVIEW_ACCOUNT_ID")
        self.site_key = config("LIBREVIEW_SITE_KEY")
        self.captcha_api_key = config("TWOCAPTCHA_API_KEY")
        self.base_url = config("LIBREVIEW_API_BASE_URL", default=self.DEFAULT_BASE_URL)

        # login creds
        self.email = config("LIBREVIEW_EMAIL")
        self.password = config("LIBREVIEW_PASSWORD")
        self.trusted_device_token = config("LIBREVIEW_TRUSTED_DEVICE_TOKEN")

        self._client: Optional[httpx.AsyncClient] = None
        self.cache_store = CacheStore("libreview")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "LibreViewClient":
        await self._get_client()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.DEFAULT_TIMEOUT,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36"
                    ),
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _auth_headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "account-id": self.account_id,  # type: ignore
        }

    async def _get_auth_token(self) -> str:
        cached = self.cache_store.get_key(self.AUTH_TOKEN_KEY)
        if cached:
            return cached.decode()

        # acquire lock
        lock = self.cache_store.set_key(
            self.AUTH_LOCK_KEY,
            "1",
            expire=self.LOCK_TTL,
            nx=True,
        )

        if not lock:
            # another worker is refreshing
            await asyncio.sleep(1)
            cached = self.cache_store.get_key(self.AUTH_TOKEN_KEY)
            if cached:
                return cached.decode()
            raise RuntimeError("LibreView auth token unavailable")

        try:
            token, ttl = await self._login_and_get_token()
            self.cache_store.set_key(self.AUTH_TOKEN_KEY, token, expire=ttl)
            return token
        finally:
            self.cache_store.delete_key(self.AUTH_LOCK_KEY)

    async def _login_and_get_token(self) -> Tuple[str, int]:
        client = await self._get_client()

        payload = {
            "email": self.email,
            "password": self.password,
            "trustedDeviceToken": self.trusted_device_token,
        }

        response = await client.post(
            f"{self.base_url}/auth/login",
            json=payload,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "product": "lv",
                "newyu-lv-web-version": "3.25.0.29",
            },
        )

        if response.status_code != 200:
            logger.error(
                "[LibreView] Login failed: status={} body={}",
                response.status_code,
                response.text[:500],
            )
        response.raise_for_status()
        data = response.json()["data"]["authTicket"]

        token = data["token"]
        expires = int(data["expires"])

        now = int(time.time())
        ttl = max(expires - now - self.TOKEN_SAFETY_MARGIN, 60)

        logger.info("[LibreView] Auth token refreshed (ttl={}s)", ttl)
        return token, ttl

    # ------------------------------------------------------------------
    # Turnstile
    # ------------------------------------------------------------------

    def _solve_turnstile_sync(self, libreview_id: str) -> str:
        page_url = f"https://www.libreview.com/patient/{libreview_id}/profile"
        logger.info("[LibreView] Solving Turnstile captcha")

        solver = TwoCaptcha(self.captcha_api_key)
        result = solver.turnstile(sitekey=self.site_key, url=page_url)

        token = result.get("code") if isinstance(result, dict) else result
        if not token:
            raise ValueError("Empty Turnstile token returned")

        return str(token)

    async def solve_turnstile(self, libreview_id: str) -> str:
        try:
            return await asyncio.to_thread(self._solve_turnstile_sync, libreview_id)
        except Exception as e:
            logger.exception("[LibreView] Turnstile solve failed")
            raise ValueError("Turnstile solving failed") from e

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    async def request_export(
        self, libreview_id: str, turnstile_token: str
    ) -> Dict[str, str]:
        client = await self._get_client()
        auth_token = await self._get_auth_token()

        response = await client.post(
            f"{self.base_url}/patients/{libreview_id}/export",
            json={"type": "glucose"},
            headers={
                **self._auth_headers(auth_token),
                "captcha-token": turnstile_token,
            },
        )

        response.raise_for_status()
        payload = response.json()

        try:
            return {
                "status_url": payload["data"]["url"],
                "auth_token": payload["ticket"]["token"],
            }
        except KeyError:
            raise ValueError("Malformed export response")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def wait_for_export_ready(
        self,
        channel_url: str,
        auth_token: str,
        poll_interval: float = 5.0,
        max_wait: float = 600.0,
    ) -> str:
        client = await self._get_client()
        headers = self._auth_headers(auth_token)

        # Trigger backend processing (best-effort)
        try:
            await client.get(channel_url, headers=headers)
        except Exception:
            logger.debug("[LibreView] Channel trigger failed (ignored)")

        status_url = channel_url.replace("/channel", "")
        deadline = time.monotonic() + max_wait

        while time.monotonic() < deadline:
            response = await client.get(status_url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                if data.get("operation") == "update":
                    csv_url = data.get("args", {}).get("url")
                    if csv_url:
                        logger.info("[LibreView] Export ready")
                        return csv_url

            await asyncio.sleep(poll_interval)

        raise TimeoutError("Export did not complete in time")

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def download_csv(self, csv_url: str) -> bytes:
        client = await self._get_client()
        response = await client.get(csv_url)
        response.raise_for_status()
        return response.content

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def sync_patient_data(self, libreview_id: str) -> bytes:
        async with self:
            turnstile = await self.solve_turnstile(libreview_id)
            export = await self.request_export(libreview_id, turnstile)
            csv_url = await self.wait_for_export_ready(
                export["status_url"], export["auth_token"], poll_interval=10.0
            )
            return await self.download_csv(csv_url)
