"""Async client for the LibreLinkUp follower JSON API.

Sibling to LibreViewClient: same Abbott backend, different endpoint family
(`/llu/*`). Used for near-real-time glucose polling — no captcha, ~5-min
cadence, returns rolling 12h of readings as JSON.

Reuses the shared follower credentials (LIBREVIEW_EMAIL / LIBREVIEW_PASSWORD).
The single follower account is "shared with" by patients via LibreLink's
share-readings flow; the API returns one connection per shared patient.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import time
from typing import Optional

import httpx
from decouple import config
from loguru import logger

from lib.core.cache_store import CacheStore


REGION_BASE_URLS = {
    "us": "https://api-us.libreview.io",
    "eu": "https://api-eu.libreview.io",
    "eu2": "https://api-eu2.libreview.io",
    "au": "https://api-au.libreview.io",
    "ap": "https://api-ap.libreview.io",
    "ca": "https://api-ca.libreview.io",
    "fr": "https://api-fr.libreview.io",
    "jp": "https://api-jp.libreview.io",
    "la": "https://api-la.libreview.io",
    "ru": "https://api.libreview.ru",
}


class LibreLinkUpClient:
    """Async client for the LibreLinkUp follower API."""

    DEFAULT_TIMEOUT = 30.0
    DEFAULT_BASE_URL = "https://api-ap.libreview.io"

    AUTH_TOKEN_KEY = "auth:token"
    AUTH_ACCOUNT_ID_KEY = "auth:account_id_sha256"
    AUTH_BASE_URL_KEY = "auth:base_url"
    AUTH_LOCK_KEY = "auth:lock"

    LOCK_TTL = 15
    TOKEN_SAFETY_MARGIN = 30

    def __init__(self):
        self.email = config("LIBREVIEW_EMAIL")
        self.password = config("LIBREVIEW_PASSWORD")
        self.base_url = config(
            "LIBREVIEW_API_BASE_URL", default=self.DEFAULT_BASE_URL
        )
        self.llu_version = config("LIBRELINKUP_VERSION", default="4.16.0")

        self._client: Optional[httpx.AsyncClient] = None
        self.cache_store = CacheStore("librelinkup")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "LibreLinkUpClient":
        await self._get_client()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.DEFAULT_TIMEOUT,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------

    def _llu_headers(
        self,
        token: Optional[str] = None,
        account_id_sha256: Optional[str] = None,
    ) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "product": "llu.android",
            "version": self.llu_version,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if account_id_sha256:
            headers["account-id"] = account_id_sha256
        return headers

    # ------------------------------------------------------------------
    # Auth (cached, lock-protected)
    # ------------------------------------------------------------------

    async def _get_auth(self) -> tuple[str, str, str]:
        """Return (token, account_id_sha256, base_url), refreshing if needed."""
        token = self.cache_store.get_key(self.AUTH_TOKEN_KEY)
        account_id = self.cache_store.get_key(self.AUTH_ACCOUNT_ID_KEY)
        base_url = self.cache_store.get_key(self.AUTH_BASE_URL_KEY)

        if token and account_id and base_url:
            return token.decode(), account_id.decode(), base_url.decode()

        lock = self.cache_store.set_key(
            self.AUTH_LOCK_KEY, "1", expire=self.LOCK_TTL, nx=True
        )
        if not lock:
            await asyncio.sleep(1)
            token = self.cache_store.get_key(self.AUTH_TOKEN_KEY)
            account_id = self.cache_store.get_key(self.AUTH_ACCOUNT_ID_KEY)
            base_url = self.cache_store.get_key(self.AUTH_BASE_URL_KEY)
            if token and account_id and base_url:
                return token.decode(), account_id.decode(), base_url.decode()
            raise RuntimeError("LibreLinkUp auth unavailable (lock held)")

        try:
            token, account_id, base_url, ttl = await self._login()
            self.cache_store.set_key(self.AUTH_TOKEN_KEY, token, expire=ttl)
            self.cache_store.set_key(
                self.AUTH_ACCOUNT_ID_KEY, account_id, expire=ttl
            )
            self.cache_store.set_key(
                self.AUTH_BASE_URL_KEY, base_url, expire=ttl
            )
            return token, account_id, base_url
        finally:
            self.cache_store.delete_key(self.AUTH_LOCK_KEY)

    async def _login(self) -> tuple[str, str, str, int]:
        """POST /llu/auth/login, follow region redirect, return derived auth."""
        client = await self._get_client()
        base_url = self.base_url

        for _ in range(3):  # bounded redirect chain
            response = await client.post(
                f"{base_url}/llu/auth/login",
                json={"email": self.email, "password": self.password},
                headers=self._llu_headers(),
            )

            if response.status_code != 200:
                logger.error(
                    "[LibreLinkUp] Login failed: status={} body={}",
                    response.status_code,
                    response.text[:500],
                )
                response.raise_for_status()

            payload = response.json()
            payload_status = payload.get("status")
            data = payload.get("data") or {}

            if data.get("redirect"):
                region = data.get("region")
                if region not in REGION_BASE_URLS:
                    raise RuntimeError(f"Unknown LibreLinkUp region: {region!r}")
                base_url = REGION_BASE_URLS[region]
                logger.info("[LibreLinkUp] Redirected to {}", base_url)
                continue

            # Soft-reject: HTTP 200 but `status != 0` means the API refused the
            # login at the application layer.
            if payload_status not in (0, None):
                min_version = data.get("minimumVersion")
                if min_version:
                    raise RuntimeError(
                        f"LibreLinkUp rejected our `version` header. "
                        f"Bump LIBRELINKUP_VERSION to >= {min_version} "
                        f"(currently {self.llu_version})."
                    )
                step = data.get("step") or {}
                step_type = step.get("type")
                partial_token = (data.get("authTicket") or {}).get("token")
                # Auto-accept periodic re-prompts (TOU, Privacy Policy, etc.).
                # HCP/pro accounts can chain multiple of these. Each step
                # returns a fresh partial JWT and possibly another step.
                if step_type and partial_token:
                    data = await self._accept_acknowledgement_chain(
                        base_url, partial_token, first_step_type=step_type
                    )
                else:
                    raise RuntimeError(
                        f"LibreLinkUp login rejected (status={payload_status}, "
                        f"step={step_type or 'unknown'}, data={data})"
                    )

            ticket = data.get("authTicket") or {}
            user = data.get("user") or {}
            token = ticket.get("token")
            user_id = user.get("id")
            expires = ticket.get("expires")

            if not token or not user_id or not expires:
                raise RuntimeError(
                    f"Malformed login response: status={payload_status} "
                    f"data_keys={list(data.keys())}"
                )

            account_id_sha256 = hashlib.sha256(
                str(user_id).encode()
            ).hexdigest()
            now = int(time.time())
            ttl = max(int(expires) - now - self.TOKEN_SAFETY_MARGIN, 60)

            logger.info(
                "[LibreLinkUp] Auth refreshed (ttl={}s, base={})", ttl, base_url
            )
            return token, account_id_sha256, base_url, ttl

        raise RuntimeError("LibreLinkUp login redirect loop")

    async def _accept_acknowledgement_chain(
        self,
        base_url: str,
        partial_token: str,
        first_step_type: str,
        max_steps: int = 5,
    ) -> dict:
        """POST through any chain of `step` acknowledgements until done.

        Abbott can require multiple acks back-to-back (TOU, then Privacy
        Policy, etc.). Each `/auth/continue/{type}` call either returns the
        upgraded ticket (status=0, no step) or another partial ticket with
        the next required step.
        """
        client = await self._get_client()
        token = partial_token
        step_type = first_step_type

        for _ in range(max_steps):
            inner, used_path = await self._post_continue(client, base_url, step_type, token)
            logger.info(
                "[LibreLinkUp] Acknowledgement '{}' accepted via {}",
                step_type,
                used_path,
            )

            next_step = (inner.get("step") or {}).get("type")
            real_token = (inner.get("authTicket") or {}).get("token")

            if not next_step and real_token:
                return inner

            if not next_step:
                raise RuntimeError(
                    f"continue/{step_type} returned no step and no token: {inner}"
                )

            # Step returned a fresh partial — chain into it.
            token = real_token or token
            step_type = next_step

        raise RuntimeError(
            f"Acknowledgement chain exceeded {max_steps} steps "
            f"(stuck on '{step_type}')"
        )

    async def _post_continue(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        step_type: str,
        partial_token: str,
    ) -> tuple[dict, str]:
        """Try LLU path then legacy fallback. Return (data_block, path_used)."""
        last_err = None
        for path in (f"/llu/auth/continue/{step_type}", f"/auth/continue/{step_type}"):
            response = await client.post(
                f"{base_url}{path}",
                json={},
                headers=self._llu_headers(token=partial_token),
            )
            if response.status_code == 200:
                payload = response.json()
                inner = payload.get("data") or {}
                if payload.get("status") in (0, None, 4):
                    # status=4 with another `step` means "ack received, here's
                    # the next required ack" — we keep going. status=0 with
                    # no step means done.
                    return inner, path
                last_err = (
                    f"{path} status={payload.get('status')} data={inner}"
                )
            else:
                last_err = (
                    f"{path} HTTP {response.status_code} "
                    f"body={response.text[:300]}"
                )
        raise RuntimeError(
            f"Could not POST continue/{step_type}: {last_err}"
        )

    def _invalidate_auth(self) -> None:
        self.cache_store.delete_key(self.AUTH_TOKEN_KEY)
        self.cache_store.delete_key(self.AUTH_ACCOUNT_ID_KEY)
        self.cache_store.delete_key(self.AUTH_BASE_URL_KEY)

    # ------------------------------------------------------------------
    # Authenticated calls
    # ------------------------------------------------------------------

    async def _authed_get(self, path: str) -> dict:
        client = await self._get_client()
        token, account_id, base_url = await self._get_auth()

        response = await client.get(
            f"{base_url}{path}",
            headers=self._llu_headers(token=token, account_id_sha256=account_id),
        )

        if response.status_code in (401, 403):
            # Either JWT expired or version header is stale. Drop cached auth
            # so the next call re-logs in. If 403 has a minimumVersion
            # payload, surface it loudly.
            self._invalidate_auth()
            body_text = response.text[:500]
            if "minimumVersion" in body_text:
                logger.error(
                    "[LibreLinkUp] {} on {} — version header rejected: {}",
                    response.status_code,
                    path,
                    body_text,
                )
            response.raise_for_status()

        response.raise_for_status()
        return response.json()

    async def connections(self) -> list[dict]:
        """List patients the shared follower account has access to."""
        payload = await self._authed_get("/llu/connections")
        return payload.get("data") or []

    async def graph(self, patient_id: str) -> dict:
        """Return rolling-12h glucose graph for a connection."""
        payload = await self._authed_get(
            f"/llu/connections/{patient_id}/graph"
        )
        return payload.get("data") or {}

    # ------------------------------------------------------------------
    # Public — normalized readings
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_factory_ts(ts: str) -> Optional[dt.datetime]:
        """FactoryTimestamp is the only UTC field. Return naive UTC datetime."""
        if not ts:
            return None
        for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"):
            try:
                return dt.datetime.strptime(ts, fmt)
            except ValueError:
                continue
        return None

    def _normalize_measurement(
        self,
        measurement: dict,
        patient_id: str,
        record_type: str,
    ) -> Optional[dict]:
        ts = self._parse_factory_ts(measurement.get("FactoryTimestamp", ""))
        value = measurement.get("ValueInMgPerDl")
        if ts is None or value is None:
            return None
        try:
            glucose_level = int(round(float(value)))
        except (TypeError, ValueError):
            return None
        return {
            "patient_id": str(patient_id),
            "time": ts,
            "glucose_level": glucose_level,
            "record_type": record_type,
            "source": "librelinkup",
        }

    def normalize_graph(self, graph_payload: dict, patient_id: str) -> list[dict]:
        """Flatten /graph response into rows for the CGM ingest pipeline.

        graphData entries → 'historic'; the live `glucoseMeasurement` → 'scan'.
        Dedup by `time` so the latest measurement doesn't double-write when it
        also sits at the tail of graphData.
        """
        rows: dict[dt.datetime, dict] = {}
        for entry in graph_payload.get("graphData") or []:
            row = self._normalize_measurement(entry, patient_id, "historic")
            if row:
                rows[row["time"]] = row

        latest = (graph_payload.get("connection") or {}).get("glucoseMeasurement")
        if latest:
            row = self._normalize_measurement(latest, patient_id, "scan")
            if row:
                rows[row["time"]] = row

        return sorted(rows.values(), key=lambda r: r["time"])

    async def fetch_readings_for_connection(
        self, llu_patient_id: str, internal_patient_id: str
    ) -> list[dict]:
        """Fetch + normalize readings for a single connection."""
        graph_payload = await self.graph(llu_patient_id)
        return self.normalize_graph(graph_payload, internal_patient_id)
