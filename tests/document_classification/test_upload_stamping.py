"""The upload flow classifies after extraction and before the Mongo write.

Flow under test (lib/services/patient_document_service.py):
    S3 upload -> extract text -> summarize -> classify -> build doc -> insert

The sweep (scripts/classify_patient_documents.py) is the backfill for
documents that predate the engine; this covers the ingest path that keeps
new uploads from ever needing it.
"""

import pytest

from lib.services.document_classification import ENGINE_VERSION
from lib.services.patient_document_service import PatientDocumentService

from . import fixtures as fx

MODULE = "lib.services.patient_document_service"


class FakeInsertResult:
    inserted_id = "doc-1"


class FakeCollection:
    """Captures exactly what the flow hands to Mongo."""

    def __init__(self):
        self.stored = None

    async def insert_one(self, doc):
        self.stored = doc
        return FakeInsertResult()


async def run_upload(monkeypatch, text: str, file_name: str = "cbc.pdf") -> dict:
    """Drive the real upload flow, stubbing only its external I/O."""
    svc = object.__new__(PatientDocumentService)
    collection = FakeCollection()
    svc.patient_document_collection = collection
    svc.s3_bucket_name = "test-bucket"
    svc.qdrant_collection_name = "patient_data"

    monkeypatch.setattr(
        f"{MODULE}.upload_file_to_s3", lambda **kw: "https://s3.test/f.pdf"
    )

    class Extractor:
        def extract(self, *a, **kw):
            return text

    svc.file_content_extractor_service = Extractor()

    async def fake_summary(_self, _text):
        return "summary text"

    async def fake_repr(_self, _summary):
        return "repr text"

    async def fake_qdrant(_self, *a, **kw):
        return None

    async def fake_profile(_patient_id):
        return None

    monkeypatch.setattr(PatientDocumentService, "_summarize_document", fake_summary)
    monkeypatch.setattr(PatientDocumentService, "_generate_text_repr", fake_repr)
    monkeypatch.setattr(PatientDocumentService, "_upsert_to_qdrant", fake_qdrant)
    monkeypatch.setattr(
        PatientDocumentService, "_build_embedding_payload", lambda *a, **kw: {}
    )

    class Profiles:
        fetch_patient_profile = staticmethod(fake_profile)

    svc.patient_profile_service = Profiles()

    await svc.upload_patient_document(
        patient_id="p1",
        file_bytes=b"bytes",
        file_name=file_name,
        content_type="application/pdf",
        document_type="report",
        uploaded_by_id="u1",
        uploaded_by_type="patient",
    )
    return collection.stored


@pytest.mark.asyncio
async def test_document_reaches_mongo_already_classified(monkeypatch):
    stored = await run_upload(monkeypatch, fx.CBC_TEXT)

    # The classification is present in the very dict handed to insert_one --
    # no second pass, no sweep needed.
    assert stored["classification"]["doc_type"] == "lab_report"
    assert stored["classification"]["engine_version"] == ENGINE_VERSION
    assert "cbc" in stored["classification"]["panels"]
    assert stored["text_raw"] == fx.CBC_TEXT


@pytest.mark.asyncio
async def test_radiology_reaches_mongo_classified(monkeypatch):
    stored = await run_upload(monkeypatch, fx.XRAY_TEXT, file_name="chest-xray.pdf")
    assert stored["classification"]["doc_type"] == "radiology"


@pytest.mark.asyncio
async def test_classifier_failure_never_breaks_the_upload(monkeypatch):
    """A broken engine costs a log line, not the patient's document."""

    def boom(*a, **kw):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(f"{MODULE}.classify_document", boom)
    stored = await run_upload(monkeypatch, fx.CBC_TEXT)

    # Document still stored, and the key is ABSENT rather than {} so the
    # sweep's {"classification": {"$exists": False}} filter still finds it.
    assert stored["text_raw"] == fx.CBC_TEXT
    assert "classification" not in stored


def test_short_text_is_stamped_unclassified_not_dropped():
    """Below MIN_TEXT_CHARS the engine returns a result, not an error."""
    svc = object.__new__(PatientDocumentService)
    result = svc._classify_document(
        extracted_text="x-ray",
        file_name="a.pdf",
        content_type="application/pdf",
        document_type="report",
    )
    assert result["doc_type"] == "unclassified"
    assert result["engine_version"] == ENGINE_VERSION
