import asyncio
from typing import Optional

import httpx
from decouple import config
from loguru import logger
from twocaptcha import TwoCaptcha

import time
from typing import Dict


class LibreViewClient:
    """Async client for interacting with LibreView API."""

    DEFAULT_TIMEOUT = 30.0
    DEFAULT_BASE_URL = "https://api-ap.libreview.io"

    def __init__(self):
        self.auth_token = config("LIBREVIEW_AUTH_TOKEN")
        self.account_id = config("LIBREVIEW_ACCOUNT_ID")
        self.site_key = config("LIBREVIEW_SITE_KEY")
        self.captcha_api_key = config("TWOCAPTCHA_API_KEY")
        self.base_url = config("LIBREVIEW_API_BASE_URL", default=self.DEFAULT_BASE_URL)

        self._client: Optional[httpx.AsyncClient] = None

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
    # Headers
    # ------------------------------------------------------------------

    def _auth_headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "account-id": self.account_id,  # type: ignore
        }

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

        response = await client.post(
            f"{self.base_url}/patients/{libreview_id}/export",
            json={"type": "glucose"},
            headers={
                **self._auth_headers(self.auth_token),  # type: ignore
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
                export["status_url"], export["auth_token"]
            )
            return await self.download_csv(csv_url)
