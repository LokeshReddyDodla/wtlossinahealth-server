"""Tests for PrescriptionExtractionService — LLM-driven prescription parsing.

Covers prompt construction, multi-image handling, response shape validation,
trace propagation, and gateway failure handling. Mocks ModelGateway so no
real LLM calls are made.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.schemas.medication import (
    ExtractedMedicine,
    ExtractedPrescription,
    MedicationDose,
    MedicationSchedule,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


def _gateway(extract_return=None, extract_side_effect=None):
    """Build a mock ModelGateway with extract() configurable per test."""
    gateway = MagicMock()

    if extract_side_effect is not None:
        gateway.extract = AsyncMock(side_effect=extract_side_effect)
    else:
        # Default: returns an empty extracted prescription with metadata
        default_extracted = extract_return or ExtractedPrescription()
        meta = SimpleNamespace(
            usage=SimpleNamespace(
                cost=SimpleNamespace(total_cost=0.0001),
                input_tokens=100,
                output_tokens=50,
            ),
            latency_ms=1234,
            model_id="gpt-4o",
            trace_id=None,
        )
        gateway.extract = AsyncMock(return_value=(default_extracted, meta))

    gateway.langfuse_trace_input = MagicMock()
    gateway.langfuse_trace_output = MagicMock()
    return gateway


def _service(gateway=None):
    from lib.services.prescription_extraction_service import PrescriptionExtractionService

    return PrescriptionExtractionService(gateway=gateway or _gateway())


# ── Happy-path extraction ───────────────────────────────────────────────────


class TestExtractHappyPath:
    @pytest.mark.asyncio
    async def test_returns_extracted_prescription(self):
        extracted = ExtractedPrescription(
            doctor_name="Dr. Smith",
            prescription_date=date(2026, 4, 1),
            medicines=[
                ExtractedMedicine(
                    name="Metformin",
                    strength="500mg",
                    doses=[MedicationDose(slot="morning", quantity=1)],
                    start_date=date(2026, 4, 1),
                ),
            ],
        )
        gateway = _gateway(extract_return=extracted)
        svc = _service(gateway)

        result = await svc.extract(image_urls=["https://example.com/rx.jpg"])

        assert isinstance(result, ExtractedPrescription)
        assert result.doctor_name == "Dr. Smith"
        assert len(result.medicines) == 1
        assert result.medicines[0].name == "Metformin"

    @pytest.mark.asyncio
    async def test_multiple_images_all_passed_to_gateway(self):
        gateway = _gateway()
        svc = _service(gateway)

        urls = [f"https://example.com/page{i}.jpg" for i in range(5)]
        await svc.extract(image_urls=urls)

        # Gateway.extract called once with messages containing all image URLs
        gateway.extract.assert_called_once()
        kwargs = gateway.extract.call_args.kwargs
        messages = kwargs["messages"]
        # System + user message
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        # User message has 1 text + N image_url parts
        user_content = messages[1]["content"]
        text_parts = [p for p in user_content if p.get("type") == "text"]
        image_parts = [p for p in user_content if p.get("type") == "image_url"]
        assert len(text_parts) == 1
        assert len(image_parts) == 5
        assert {p["image_url"]["url"] for p in image_parts} == set(urls)

    @pytest.mark.asyncio
    async def test_uses_structured_analysis_task(self):
        from lib.ai_foundation.models.registry import ModelTask

        gateway = _gateway()
        svc = _service(gateway)
        await svc.extract(image_urls=["x"])

        kwargs = gateway.extract.call_args.kwargs
        assert kwargs["task"] == ModelTask.STRUCTURED_ANALYSIS

    @pytest.mark.asyncio
    async def test_uses_extracted_prescription_response_model(self):
        gateway = _gateway()
        svc = _service(gateway)
        await svc.extract(image_urls=["x"])

        kwargs = gateway.extract.call_args.kwargs
        assert kwargs["response_model"] is ExtractedPrescription

    @pytest.mark.asyncio
    async def test_pins_to_gpt_4o(self):
        gateway = _gateway()
        svc = _service(gateway)
        await svc.extract(image_urls=["x"])

        kwargs = gateway.extract.call_args.kwargs
        assert kwargs["model_id"] == "gpt-4o"


# ── Trace propagation ───────────────────────────────────────────────────────


class TestTracePropagation:
    @pytest.mark.asyncio
    async def test_trace_id_passed_to_extract(self):
        gateway = _gateway()
        svc = _service(gateway)
        await svc.extract(image_urls=["x"])

        kwargs = gateway.extract.call_args.kwargs
        assert "trace_id" in kwargs
        assert kwargs["trace_id"]  # uuid string

    @pytest.mark.asyncio
    async def test_trace_input_called_before_extract(self):
        gateway = _gateway()
        svc = _service(gateway)
        await svc.extract(image_urls=["a", "b"])

        gateway.langfuse_trace_input.assert_called_once()
        call = gateway.langfuse_trace_input.call_args
        assert call.kwargs["name"] == "prescription-extraction"
        assert "2 image" in call.kwargs["input_text"]

    @pytest.mark.asyncio
    async def test_trace_output_called_after_extract(self):
        gateway = _gateway()
        svc = _service(gateway)
        await svc.extract(image_urls=["x"])

        gateway.langfuse_trace_output.assert_called_once()
        meta = gateway.langfuse_trace_output.call_args.kwargs["metadata"]
        assert "cost_usd" in meta
        assert "input_tokens" in meta
        assert "output_tokens" in meta
        assert "model_id" in meta
        assert "latency_ms" in meta

    @pytest.mark.asyncio
    async def test_trace_id_consistent_input_extract_output(self):
        gateway = _gateway()
        svc = _service(gateway)
        await svc.extract(image_urls=["x"])

        in_trace = gateway.langfuse_trace_input.call_args.kwargs["trace_id"]
        ex_trace = gateway.extract.call_args.kwargs["trace_id"]
        out_trace = gateway.langfuse_trace_output.call_args.kwargs["trace_id"]
        assert in_trace == ex_trace == out_trace


# ── Empty / edge-case input ────────────────────────────────────────────────


class TestEmptyAndEdgeInputs:
    @pytest.mark.asyncio
    async def test_zero_images(self):
        gateway = _gateway()
        svc = _service(gateway)
        result = await svc.extract(image_urls=[])
        # Service still calls gateway with no images — the validation that
        # rejects "no medicines" lives in the router, not the service.
        assert isinstance(result, ExtractedPrescription)

    @pytest.mark.asyncio
    async def test_large_image_count(self):
        """LLM extraction with many pages (booklet prescription)."""
        gateway = _gateway()
        svc = _service(gateway)
        await svc.extract(image_urls=[f"u{i}" for i in range(20)])

        user_content = gateway.extract.call_args.kwargs["messages"][1]["content"]
        image_parts = [p for p in user_content if p.get("type") == "image_url"]
        assert len(image_parts) == 20

    @pytest.mark.asyncio
    async def test_extracted_zero_medicines_returned_as_is(self):
        """Service does NOT validate medicine count — that's the router's job."""
        gateway = _gateway(extract_return=ExtractedPrescription(medicines=[]))
        svc = _service(gateway)
        result = await svc.extract(image_urls=["x"])
        assert result.medicines == []


# ── Gateway failure / propagation ───────────────────────────────────────────


class TestGatewayFailures:
    @pytest.mark.asyncio
    async def test_gateway_raises_propagates(self):
        from lib.ai_foundation.models.registry import ModelGatewayError

        gateway = _gateway(extract_side_effect=ModelGatewayError("all fallbacks exhausted"))
        svc = _service(gateway)

        with pytest.raises(ModelGatewayError):
            await svc.extract(image_urls=["x"])

    @pytest.mark.asyncio
    async def test_generic_exception_propagates(self):
        gateway = _gateway(extract_side_effect=ValueError("malformed"))
        svc = _service(gateway)

        with pytest.raises(ValueError, match="malformed"):
            await svc.extract(image_urls=["x"])


# ── Various prescription shapes round-trip through schema ───────────────────


class TestExtractedPrescriptionShapes:
    """Confirms the response_model handles every legitimate prescription
    shape the prompt can produce. These exercise the ExtractedPrescription
    schema rather than the gateway, but validate end-to-end realism."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "extracted",
        [
            # Basic single med, daily schedule
            ExtractedPrescription(
                medicines=[
                    ExtractedMedicine(
                        name="Metformin",
                        strength="500mg",
                        doses=[MedicationDose(slot="morning", quantity=1)],
                        start_date=date(2026, 4, 1),
                    ),
                ],
            ),
            # Multi-slot dosing (1-0-1)
            ExtractedPrescription(
                medicines=[
                    ExtractedMedicine(
                        name="Atorvastatin",
                        strength="10mg",
                        doses=[
                            MedicationDose(slot="morning", quantity=1),
                            MedicationDose(slot="evening", quantity=1),
                        ],
                    ),
                ],
            ),
            # SOS / PRN — no doses, is_sos=True
            ExtractedPrescription(
                medicines=[
                    ExtractedMedicine(
                        name="Paracetamol",
                        strength="500mg",
                        is_sos=True,
                        doses=[],
                    ),
                ],
            ),
            # Weekly schedule (MWF)
            ExtractedPrescription(
                medicines=[
                    ExtractedMedicine(
                        name="Methotrexate",
                        strength="15mg",
                        schedule=MedicationSchedule(type="weekly", days_of_week=[0, 2, 4]),
                    ),
                ],
            ),
            # Interval schedule (every 3 days)
            ExtractedPrescription(
                medicines=[
                    ExtractedMedicine(
                        name="Iron",
                        strength="325mg",
                        schedule=MedicationSchedule(
                            type="interval",
                            interval_days=3,
                            interval_anchor=date(2026, 4, 1),
                        ),
                    ),
                ],
            ),
            # Fractional quantity (half tablet)
            ExtractedPrescription(
                medicines=[
                    ExtractedMedicine(
                        name="Aspirin",
                        strength="81mg",
                        doses=[MedicationDose(slot="morning", quantity=0.5)],
                    ),
                ],
            ),
            # Follow-up required
            ExtractedPrescription(
                doctor_name="Dr. Wong",
                prescription_date=date(2026, 4, 1),
                medicines=[
                    ExtractedMedicine(name="Med1"),
                ],
                follow_up_required=True,
                follow_up_date=date(2026, 5, 1),
            ),
            # Multiple medicines
            ExtractedPrescription(
                medicines=[
                    ExtractedMedicine(name="Med1", strength="100mg"),
                    ExtractedMedicine(name="Med2", strength="200mg"),
                    ExtractedMedicine(name="Med3", strength="300mg"),
                ],
            ),
            # Empty / non-prescription image
            ExtractedPrescription(medicines=[]),
        ],
    )
    async def test_extract_returns_valid_shape(self, extracted):
        gateway = _gateway(extract_return=extracted)
        svc = _service(gateway)
        result = await svc.extract(image_urls=["x"])
        assert result.model_dump() == extracted.model_dump()
