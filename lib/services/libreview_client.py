"""LibreView API Client - handles export requests and Cloudflare Turnstile solving."""

import asyncio
from typing import Optional

import httpx
from decouple import config
from loguru import logger
from twocaptcha import TwoCaptcha


class LibreViewClient:
    """Client for interacting with LibreView API."""

    def __init__(self):
        self.auth_token = config("LIBREVIEW_AUTH_TOKEN")
        self.account_id = config("LIBREVIEW_ACCOUNT_ID")
        self.site_key = config("LIBREVIEW_SITE_KEY")
        self.captcha_api_key = config("TWOCAPTCHA_API_KEY")
        self.base_url = config(
            "LIBREVIEW_API_BASE_URL", default="https://api-ap.libreview.io"
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def solve_turnstile(self, libreview_id: str) -> str:
        """Solve Cloudflare Turnstile captcha using 2captcha."""
        page_url = f"https://www.libreview.com/patient/{libreview_id}/profile"

        logger.info(f"[LibreViewClient] Solving Cloudflare Turnstile for {page_url}")

        solver = TwoCaptcha(self.captcha_api_key)

        try:
            result = solver.turnstile(
                sitekey=self.site_key,
                url=page_url,
            )

            token = result.get("code") if isinstance(result, dict) else result

            if not token:
                raise ValueError("Turnstile solving returned empty token")

            logger.info("[LibreViewClient] Cloudflare Turnstile solved successfully")
            return str(token)

        except Exception as e:
            logger.error(f"[LibreViewClient] Turnstile solving failed: {e}")
            raise

    async def request_export(self, libreview_id: str, turnstile_token: str) -> dict:
        """Request a LibreView data export."""
        url = f"{self.base_url}/patients/{libreview_id}/export"
        payload = {"type": "glucose"}

        logger.info(f"[LibreViewClient] Requesting export for patient {libreview_id}")

        client = await self._get_client()

        response = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.auth_token}",
                "account-id": self.account_id,
                "captcha-token": turnstile_token,
            },
        )

        response.raise_for_status()
        result = response.json()

        logger.debug(f"[LibreViewClient] Export response: {result}")

        status_url = result.get("data", {}).get("url")
        auth_token = result.get("ticket", {}).get("token")

        if not status_url or not auth_token:
            raise ValueError("Export response missing required fields")

        logger.info(f"[LibreViewClient] Export initiated: {status_url}")

        return {
            "status_url": status_url,
            "auth_token": auth_token,
        }

    async def wait_for_export_ready(
        self,
        original_url: str,
        auth_token: str,
        poll_interval: float = 5.0,
        max_wait: float = 600.0,
    ) -> str:
        """Wait for export to be ready by polling status endpoint."""
        logger.info(f"[LibreViewClient] Triggering backend processing: {original_url}")

        client = await self._get_client()

        try:
            await client.get(
                original_url,
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "account-id": self.account_id,
                },
            )
        except Exception as e:
            logger.warning(f"[LibreViewClient] Channel trigger warning: {e}")

        status_url = original_url.replace("/channel", "")
        logger.info(f"[LibreViewClient] Polling for export readiness: {status_url}")

        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed > max_wait:
                raise TimeoutError(f"Export did not complete within {max_wait}s")

            try:
                response = await client.get(
                    status_url,
                    headers={
                        "Authorization": f"Bearer {auth_token}",
                        "account-id": self.account_id,
                    },
                )

                if response.status_code == 200:
                    status_data = response.json()
                    operation = status_data.get("operation")

                    logger.debug(
                        f"[LibreViewClient] Poll response operation: {operation}"
                    )

                    if operation == "update":
                        csv_url = status_data.get("args", {}).get("url")
                        if csv_url:
                            logger.info(f"[LibreViewClient] Export ready: {csv_url}")
                            return csv_url

            except Exception as e:
                logger.warning(f"[LibreViewClient] Poll error: {e}")

            await asyncio.sleep(poll_interval)

    async def download_csv(self, csv_url: str) -> bytes:
        """Download the CSV file from LibreView."""
        logger.info(f"[LibreViewClient] Downloading CSV from {csv_url}")

        client = await self._get_client()

        response = await client.get(csv_url)
        response.raise_for_status()

        csv_data = response.content
        logger.info(f"[LibreViewClient] Downloaded {len(csv_data)} bytes")

        return csv_data

    async def sync_patient_data(self, libreview_id: str) -> bytes:
        """Full sync workflow: solve captcha, request export, wait, download."""
        try:
            # Step 1: Solve Turnstile (sync call)
            turnstile_token = self.solve_turnstile(libreview_id)

            # Step 2: Request export
            export_result = await self.request_export(libreview_id, turnstile_token)

            # Step 3: Wait for export to be ready
            csv_url = await self.wait_for_export_ready(
                export_result["status_url"],
                export_result["auth_token"],
            )

            # Step 4: Download CSV
            csv_data = await self.download_csv(csv_url)

            return csv_data

        finally:
            await self.close()
