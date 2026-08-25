from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from lib.models.patient_body_composition_record import (
    PatientBodyCompositionRecord,
)
from lib.schemas.body_composition import (
    BodyCompositionExtraction,
    BodyCompositionMeasurement,
    MeasurementMethod,
)
from lib.services.body_composition.extraction import (
    SYSTEM_PROMPT,
    BodyCompositionExtractionService,
)
from lib.services.body_composition.service import (
    BodyCompositionService,
    _normalize,
    _project_columns,
    _validation_issues,
)


def _extraction(**overrides) -> BodyCompositionExtraction:
    values = {
        "manufacturer": "  INBODY  ",
        "device_model": "380",
        "measurement_method": MeasurementMethod.BIA_MULTIFREQUENCY,
        "test_datetime": datetime(2026, 5, 11, 12, 38),
        "measurements": [
            BodyCompositionMeasurement(
                key="weight", value=160.276, unit="lb", confidence=0.99
            ),
            BodyCompositionMeasurement(
                key="pbf", value=14.4, unit="%", confidence=0.99
            ),
        ],
        "extraction_confidence": 0.99,
    }
    values.update(overrides)
    return BodyCompositionExtraction(**values)


def test_normalizes_vendor_string_metric_alias_and_mass_unit() -> None:
    normalized, vendor = _normalize(_extraction())

    assert normalized.manufacturer == "InBody"
    assert normalized.measurements[0].unit == "kg"
    assert normalized.measurements[0].value == pytest.approx(72.7, abs=0.01)
    assert normalized.measurements[1].key == "percent_body_fat"
    assert vendor == []


def test_reference_range_converts_with_the_value_not_the_canonical_unit() -> None:
    data = _extraction(
        measurements=[
            BodyCompositionMeasurement(
                key="weight",
                value=160.0,
                unit="lb",
                reference_low=130.0,
                reference_high=180.0,
                confidence=0.99,
            ),
        ]
    )
    normalized, _ = _normalize(data)
    weight = normalized.measurements[0]

    assert weight.unit == "kg"
    assert weight.reference_low == pytest.approx(58.97, abs=0.05)
    assert weight.reference_high == pytest.approx(81.65, abs=0.05)


def test_unmappable_metric_splits_into_vendor_long_tail() -> None:
    data = _extraction(
        measurements=[
            BodyCompositionMeasurement(
                key="weight", value=72.7, unit="kg", confidence=0.99
            ),
            BodyCompositionMeasurement(
                key="inbody_secret_index", value=42, confidence=0.9
            ),
        ]
    )
    normalized, vendor = _normalize(data)

    assert [m.key for m in normalized.measurements] == ["weight"]
    assert [m.key for m in vendor] == ["inbody_secret_index"]


def test_projects_canonical_measurements_into_typed_columns() -> None:
    normalized, _ = _normalize(_extraction())

    columns = _project_columns(normalized)

    assert columns["weight_kg"] == pytest.approx(72.7, abs=0.01)
    assert columns["percent_body_fat"] == 14.4


def test_generic_dxa_record_does_not_require_inbody_specific_metrics() -> None:
    data = BodyCompositionExtraction(
        manufacturer="Hologic",
        device_model="Horizon",
        measurement_method=MeasurementMethod.DXA,
        measurements=[
            BodyCompositionMeasurement(
                key="weight", value=72.7, unit="kg", confidence=0.98
            ),
            BodyCompositionMeasurement(
                key="body_fat_mass", value=10.5, unit="kg", confidence=0.98
            ),
        ],
        extraction_confidence=0.98,
    )

    assert _validation_issues(data, include_confidence=True) == []


def test_low_confidence_is_review_metadata_not_confirmation_structure() -> (
    None
):
    data = _extraction(extraction_confidence=0.6)
    data.measurements[0].confidence = 0.5

    normalized, _ = _normalize(data)

    assert "low_confidence:weight" in _validation_issues(
        normalized, include_confidence=True
    )
    assert _validation_issues(normalized, include_confidence=False) == []


@pytest.mark.asyncio
async def test_extractor_uses_one_generic_gateway_call_with_langfuse() -> None:
    gateway = Mock()
    gateway.extract = AsyncMock(
        return_value=(
            _extraction(),
            SimpleNamespace(
                model_id="gpt-5.2",
                latency_ms=900,
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=50,
                    cost=SimpleNamespace(total_cost=0.01),
                ),
            ),
        )
    )
    service = BodyCompositionExtractionService(gateway)

    result = await service.extract(
        file_bytes=b"image",
        content_type="image/jpeg",
        patient_id="patient-1",
    )

    assert result.measurement_method == MeasurementMethod.BIA_MULTIFREQUENCY
    gateway.extract.assert_awaited_once()
    gateway.set_langfuse_context.assert_called_once()
    gateway.langfuse_trace_input.assert_called_once()
    gateway.langfuse_trace_output.assert_called_once()
    assert "any manufacturer" in SYSTEM_PROMPT
    assert "Never assume" in SYSTEM_PROMPT


def test_trends_block_cross_method_comparison() -> None:
    rows = [
        PatientBodyCompositionRecord(
            record_id=uuid4(),
            test_datetime=datetime(2026, 1, 1),
            measurement_method="bia_multifrequency",
            manufacturer="InBody",
            device_model="380",
            weight_kg=75,
        ),
        PatientBodyCompositionRecord(
            record_id=uuid4(),
            test_datetime=datetime(2026, 2, 1),
            measurement_method="dxa",
            manufacturer="Hologic",
            device_model="Horizon",
            weight_kg=73,
        ),
    ]

    trends = BodyCompositionService._compute_trends(rows)

    assert trends["record_count"] == 2
    assert trends["series"]["weight"][0]["value"] == 75
    assert trends["comparison"]["comparable"] is False
    assert trends["comparison"]["reason"] == "measurement_method_changed"
