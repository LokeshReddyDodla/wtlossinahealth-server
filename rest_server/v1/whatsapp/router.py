"""
WhatsApp Cloud API webhook — connects patients to the health agent via WhatsApp.

Endpoints:
    GET  /whatsapp/webhook — Meta verification handshake
    POST /whatsapp/webhook — Receive incoming messages, route to HealthQueryAgent
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime

import httpx
from decouple import config
from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.ai_foundation.agents.health_query import HealthQueryAgent
from lib.ai_foundation.agents.state import AgentContext, AgentInput, RequestPriority
from lib.core.container import container
from lib.dependencies.database import get_async_postgres_session
from lib.models.patient import Patient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])

WHATSAPP_VERIFY_TOKEN = config("WHATSAPP_VERIFY_TOKEN", default="")
WHATSAPP_ACCESS_TOKEN = config("WHATSAPP_ACCESS_TOKEN", default="")
WHATSAPP_PHONE_NUMBER_ID = config("WHATSAPP_PHONE_NUMBER_ID", default="")
WHATSAPP_APP_SECRET = config("WHATSAPP_APP_SECRET", default="")

GRAPH_API_URL = "https://graph.facebook.com/v22.0"


# -- Helpers ------------------------------------------------------------------


def _verify_payload_signature(payload: bytes, signature_header: str) -> bool:
    """Verify the X-Hub-Signature-256 header from Meta."""
    if not WHATSAPP_APP_SECRET or not signature_header:
        return False
    expected = hmac.new(
        WHATSAPP_APP_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


async def _lookup_patient_by_phone(phone: str) -> Patient | None:
    """Find a patient by their phone number (E.164 without '+')."""
    async with get_async_postgres_session() as session:
        result = await session.execute(
            select(Patient).where(Patient.phone_number == phone)
        )
        return result.scalar_one_or_none()


async def _send_whatsapp_message(to: str, text: str) -> None:
    """Send a text message back via WhatsApp Cloud API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GRAPH_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
        )
        if resp.status_code != 200:
            logger.error("WhatsApp send failed: %s %s", resp.status_code, resp.text)


async def _mark_as_read(message_id: str) -> None:
    """Mark an incoming message as read (blue ticks)."""
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{GRAPH_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            },
        )


def _get_agent() -> HealthQueryAgent:
    return container.resolve(HealthQueryAgent)


# -- Endpoints ----------------------------------------------------------------


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> Response:
    """Meta webhook verification handshake."""
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified")
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_message(request: Request) -> dict:
    """Handle incoming WhatsApp messages."""
    body = await request.body()

    if WHATSAPP_APP_SECRET:
        signature = request.headers.get("x-hub-signature-256", "")
        if not _verify_payload_signature(body, signature):
            raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()

    entry = data.get("entry", [])
    if not entry:
        return {"status": "ok"}

    for e in entry:
        for change in e.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])

            for msg in messages:
                if msg.get("type") != "text":
                    continue

                sender_phone = msg["from"]
                message_text = msg["text"]["body"]
                message_id = msg["id"]

                await _mark_as_read(message_id)
                await _process_patient_message(sender_phone, message_text)

    return {"status": "ok"}


async def _process_patient_message(phone: str, message: str) -> None:
    """Look up patient by phone, run health agent, reply."""
    patient = await _lookup_patient_by_phone(phone)

    if not patient:
        await _send_whatsapp_message(
            phone,
            "Welcome! It looks like you're not registered with AiHealth yet. "
            "Please download the AiHealth app and sign up to get started.",
        )
        return

    patient_id = str(patient.patient_id)
    thread_id = f"bot:patient:{patient_id}"

    metadata: dict = {}
    if patient.timezone:
        metadata["local_time"] = datetime.now().isoformat()
    metadata["channel"] = "whatsapp"

    agent_input = AgentInput(
        message=message,
        context=AgentContext(
            patient_id=patient_id,
            user_id=patient_id,
            user_role="patient",
            thread_id=thread_id,
            patient_ids=[patient_id],
            priority=RequestPriority.NORMAL,
            timezone=patient.timezone,
            metadata=metadata,
        ),
        stream=False,
    )

    try:
        agent = _get_agent()
        output = await agent.run(agent_input)
        response_text = output.message
    except Exception:
        logger.exception("Health agent error for WhatsApp patient %s", patient_id)
        response_text = (
            "I'm having trouble processing your request right now. "
            "Please try again in a moment."
        )

    await _send_whatsapp_message(phone, response_text)
