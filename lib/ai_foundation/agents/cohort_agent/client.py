"""Internal AIHealth API client for the cohort agent.

The agent runs *inside* aihealth-server, so its tools call the backend's own
endpoints over loopback (http://localhost:8000 by default) — NOT the public
Cloudflare URL (which would loop through the edge and get bot-challenged). The
caller's JWT + device id are forwarded so every call is scoped to the same
care provider, exactly as if the browser had made it.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

# Loopback base for in-process API calls. Override with COHORT_AGENT_API_BASE.
INTERNAL_API_BASE = os.getenv("COHORT_AGENT_API_BASE", "http://localhost:8000").rstrip("/")

_RETRY_STATUSES = {502, 503, 504}


class InternalAPIClient:
    """Authenticated, loopback HTTP client used by the agent's tools."""

    def __init__(self, token: str, device_id: str | None, base_url: str | None = None) -> None:
        self.base_url = (base_url or INTERNAL_API_BASE).rstrip("/")
        self.token = token
        self.device_id = device_id
        self._http = httpx.Client(timeout=60.0)

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.device_id:
            h["x-device-id"] = self.device_id
        return h

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET an API path and return parsed JSON, unwrapping the standard
        ``{status, data, message}`` envelope to ``data`` when present."""
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                r = self._http.get(url, params=params, headers=self._headers())
            except httpx.TransportError as e:  # transient network blip
                last_exc = e
                time.sleep(0.4 * (attempt + 1))
                continue
            if r.status_code in _RETRY_STATUSES and attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            r.raise_for_status()
            body = r.json()
            if (
                isinstance(body, dict)
                and "data" in body
                and set(body.keys()) <= {"status", "version", "provenance", "data", "message"}
            ):
                return body["data"]
            return body
        if last_exc:
            raise last_exc
        raise RuntimeError(f"GET {path} failed after retries")

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:  # noqa: BLE001
            pass
