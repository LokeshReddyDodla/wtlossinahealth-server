"""WhatsApp webhooks must fail closed — unsigned requests can impersonate
any patient whose phone number is known."""

from __future__ import annotations

import hashlib
import hmac

import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

# rest_server is not an importable package under pytest (no top-level
# __init__.py) — load the router module directly by path.
_ROUTER_PATH = (
    Path(__file__).resolve().parents[2] / "rest_server" / "v1" / "whatsapp" / "router.py"
)
_spec = importlib.util.spec_from_file_location("whatsapp_router_under_test", _ROUTER_PATH)
wa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wa)


class _StubRequest:
    def __init__(self, body: bytes = b"{}", headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body

    async def json(self):
        return {}

    async def form(self):
        return {}


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_payload_signature(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_APP_SECRET", "s3cret")
    body = b'{"entry": []}'
    assert wa._verify_payload_signature(body, _sign(body, "s3cret")) is True
    assert wa._verify_payload_signature(body, _sign(body, "wrong")) is False
    assert wa._verify_payload_signature(body, "") is False


@pytest.mark.asyncio
async def test_meta_webhook_rejects_when_secret_missing(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_APP_SECRET", "")
    with pytest.raises(HTTPException) as exc:
        await wa.receive_message(_StubRequest())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_meta_webhook_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_APP_SECRET", "s3cret")
    req = _StubRequest(b'{"entry": []}', {"x-hub-signature-256": "sha256=deadbeef"})
    with pytest.raises(HTTPException) as exc:
        await wa.receive_message(req)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_meta_webhook_accepts_valid_signature(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_APP_SECRET", "s3cret")
    body = b'{"entry": []}'
    req = _StubRequest(body, {"x-hub-signature-256": _sign(body, "s3cret")})
    result = await wa.receive_message(req)
    assert result == {"status": "ok"}  # empty entry short-circuits after auth


@pytest.mark.asyncio
async def test_twilio_webhook_rejects_when_token_missing(monkeypatch):
    monkeypatch.setattr(wa, "TWILIO_AUTH_TOKEN", "")
    with pytest.raises(HTTPException) as exc:
        await wa.twilio_receive_message(_StubRequest(), Body="hi", From="whatsapp:+911234567890")
    assert exc.value.status_code == 403
