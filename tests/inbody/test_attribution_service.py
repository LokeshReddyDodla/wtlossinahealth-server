"""Unit tests for InbodyAttributionService (Mongo mocked)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from lib.services.inbody.attribution_service import InbodyAttributionService


def _service():
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    collection.update_one = AsyncMock()
    return InbodyAttributionService(collection), collection


class TestReads:
    @pytest.mark.asyncio
    async def test_get_for_report_strips_mongo_id(self):
        service, collection = _service()
        collection.find_one = AsyncMock(
            return_value={"_id": "x", "status": "completed"}
        )
        doc = await service.get_for_report(uuid4(), uuid4())
        assert doc == {"status": "completed"}

    @pytest.mark.asyncio
    async def test_get_latest_sorts_by_generated_at(self):
        service, collection = _service()
        patient_id = uuid4()
        await service.get_latest(patient_id)
        collection.find_one.assert_awaited_once_with(
            {"patient_id": str(patient_id)},
            sort=[("generated_at", -1)],
        )

    @pytest.mark.asyncio
    async def test_missing_doc_returns_none(self):
        service, _ = _service()
        assert await service.get_for_report(uuid4(), uuid4()) is None


class TestWrites:
    @pytest.mark.asyncio
    async def test_save_upserts_completed_doc(self):
        service, collection = _service()
        patient_id, report_id = uuid4(), uuid4()

        await service.save(
            patient_id,
            report_id,
            analysis_text="Muscle preserved while fat dropped.",
            previous_report_id="prev-id",
            period={"start": "2026-01-10", "end": "2026-02-10"},
            deltas={"weight": {"delta": -3.1}},
        )

        args, kwargs = collection.update_one.call_args
        query, update = args
        assert query == {
            "patient_id": str(patient_id),
            "report_id": str(report_id),
        }
        assert kwargs["upsert"] is True
        set_fields = update["$set"]
        assert set_fields["status"] == "completed"
        assert set_fields["analysis_text"].startswith("Muscle preserved")
        assert set_fields["previous_report_id"] == "prev-id"
        assert set_fields["is_baseline"] is False

    @pytest.mark.asyncio
    async def test_baseline_save(self):
        service, collection = _service()
        await service.save(
            uuid4(),
            uuid4(),
            analysis_text="First scan — baseline.",
            previous_report_id=None,
            period=None,
            deltas={},
            is_baseline=True,
        )
        set_fields = collection.update_one.call_args[0][1]["$set"]
        assert set_fields["is_baseline"] is True
        assert set_fields["previous_report_id"] is None

    @pytest.mark.asyncio
    async def test_mark_generating_then_failed(self):
        service, collection = _service()
        patient_id, report_id = uuid4(), uuid4()

        await service.mark_generating(patient_id, report_id)
        set_fields = collection.update_one.call_args[0][1]["$set"]
        assert set_fields["status"] == "generating"
        assert set_fields["error"] is None

        await service.mark_failed(patient_id, report_id, "boom " * 200)
        set_fields = collection.update_one.call_args[0][1]["$set"]
        assert set_fields["status"] == "failed"
        assert len(set_fields["error"]) <= 500
