"""Medical document processing tasks (findings extraction + overview rebuild)."""

from lib.workers.tasks.medical_documents.extract_findings import (
    extract_document_findings,
)
from lib.workers.tasks.medical_documents.rebuild_overview import (
    rebuild_patient_documents_overview,
)

__all__ = [
    "extract_document_findings",
    "rebuild_patient_documents_overview",
    "get_tasks",
]


def get_tasks():
    """Return all medical-document tasks for ARQ worker."""
    return [
        extract_document_findings,
        rebuild_patient_documents_overview,
    ]
