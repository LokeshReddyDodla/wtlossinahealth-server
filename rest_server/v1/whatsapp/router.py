"""
WhatsApp webhook endpoints — connects patients to the health agent via WhatsApp.

Endpoints:
    GET  /whatsapp/webhook         — Meta verification handshake
    POST /whatsapp/webhook         — Meta Cloud API incoming messages
    POST /whatsapp/twilio/webhook  — Twilio sandbox incoming messages
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime

import httpx
from decouple import config
from fastapi import APIRouter, Form, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.rest import Client as TwilioClient

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

TWILIO_ACCOUNT_SID = config("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN = config("TWILIO_AUTH_TOKEN", default="")
TWILIO_WHATSAPP_FROM = config("TWILIO_WHATSAPP_FROM", default="")

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


async def _react_to_message(to: str, message_id: str, emoji: str) -> None:
    """React to a message with an emoji. Pass empty string to remove reaction."""
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{GRAPH_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "reaction",
                "reaction": {"message_id": message_id, "emoji": emoji},
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

    # Fail closed: an unsigned webhook would let anyone chat as any patient
    # whose phone number they know. No secret configured = endpoint disabled.
    if not WHATSAPP_APP_SECRET:
        logger.error("WHATSAPP_APP_SECRET not configured — rejecting webhook")
        raise HTTPException(status_code=403, detail="Webhook not configured")
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
                sender_phone = msg["from"]
                message_id = msg["id"]

                if msg.get("type") != "text":
                    await _mark_as_read(message_id)
                    await _send_whatsapp_message(
                        sender_phone,
                        "I can only read text messages for now. "
                        "Please type your question and I'll be happy to help!",
                    )
                    continue

                message_text = msg["text"]["body"]

                await _mark_as_read(message_id)
                await _react_to_message(sender_phone, message_id, "⏳")
                await _process_patient_message(sender_phone, message_text, message_id)

    return {"status": "ok"}


async def _process_patient_message(
    phone: str, message: str, message_id: str | None = None
) -> None:
    """Look up patient by phone, run health agent, reply."""
    patient = await _lookup_patient_by_phone(phone)

    if not patient:
        if message_id:
            await _react_to_message(phone, message_id, "")
        await _send_whatsapp_message(
            phone,
            "Welcome! It looks like you're not registered with AiHealth yet. "
            "Please download the AiHealth app and sign up to get started.",
        )
        return

    patient_id = str(patient.patient_id)
    thread_id = f"bot:patient:{patient_id}"

    metadata: dict = {"channel": "whatsapp", "tier": "basic"}
    if patient.timezone:
        metadata["local_time"] = datetime.now().isoformat()

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

    output = None
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

    if message_id:
        await _react_to_message(phone, message_id, "")
    # Companion bubbles: send each part as its own WhatsApp message.
    bubbles = ((output.data or {}).get("messages") if output else None) or [response_text]
    for bubble in bubbles:
        await _send_whatsapp_message(phone, bubble)


# -- Twilio Sandbox -----------------------------------------------------------


def _normalize_twilio_phone(wa_id: str) -> str:
    """Convert 'whatsapp:+919876543210' → '919876543210' for patient lookup."""
    return wa_id.replace("whatsapp:", "").replace("+", "")


def _split_message(text: str, limit: int = 1500) -> list[str]:
    """Split text into chunks at paragraph boundaries, staying under limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) + 2 > limit:
            chunks.append(current.strip())
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text[:limit]]


async def _send_twilio_message(to: str, text: str) -> None:
    """Send a WhatsApp message via Twilio, splitting if over 1600 chars."""
    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        for chunk in _split_message(text):
            client.messages.create(
                from_=TWILIO_WHATSAPP_FROM,
                to=to,
                body=chunk,
            )
    except Exception:
        logger.exception("Twilio WhatsApp send failed to %s", to)


@router.post("/twilio/webhook")
async def twilio_receive_message(
    request: Request,
    Body: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
    NumMedia: int = Form(0),
) -> Response:
    """Handle incoming WhatsApp messages from Twilio sandbox."""
    # Fail closed: unsigned requests could impersonate any patient by phone.
    if not TWILIO_AUTH_TOKEN:
        logger.error("TWILIO_AUTH_TOKEN not configured — rejecting webhook")
        raise HTTPException(status_code=403, detail="Webhook not configured")
    from twilio.request_validator import RequestValidator

    form = await request.form()
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    if not validator.validate(
        str(request.url),
        dict(form),
        request.headers.get("X-Twilio-Signature", ""),
    ):
        raise HTTPException(status_code=403, detail="Invalid signature")

    if not From:
        return Response(content="<Response></Response>", media_type="application/xml")

    if NumMedia > 0 and not Body:
        await _send_twilio_message(
            From,
            "I can only read text messages for now. "
            "Please type your question and I'll be happy to help!",
        )
        return Response(content="<Response></Response>", media_type="application/xml")

    if not Body:
        return Response(content="<Response></Response>", media_type="application/xml")

    phone = _normalize_twilio_phone(From)
    logger.info("Twilio WhatsApp message from %s… (%d chars)", phone[:6], len(Body))

    patient = await _lookup_patient_by_phone(phone)

    if not patient:
        await _send_twilio_message(
            From,
            "Welcome! It looks like you're not registered with AiHealth yet. "
            "Please download the AiHealth app and sign up to get started.",
        )
        return Response(content="<Response></Response>", media_type="application/xml")

    patient_id = str(patient.patient_id)
    thread_id = f"bot:patient:{patient_id}"

    await _send_twilio_message(From, "⏳")

    metadata: dict = {"channel": "whatsapp", "tier": "basic"}
    if patient.timezone:
        metadata["local_time"] = datetime.now().isoformat()

    agent_input = AgentInput(
        message=Body,
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

    output = None
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

    # Companion bubbles: send each part as its own message (length-split per part).
    bubbles = ((output.data or {}).get("messages") if output else None) or [response_text]
    for bubble in bubbles:
        for chunk in _split_message(bubble):
            await _send_twilio_message(From, chunk)
    return Response(content="<Response></Response>", media_type="application/xml")
