"""Medical documents sub-feature of the profile agent.

Wraps the existing PatientDocumentService with patient-facing helpers
(timeline, overview reads, soft delete, skip-onboarding) and adds the
structured findings extraction + cross-document overview rebuild
pipelines.
"""

from lib.services.profile_agent.documents.linker import group_findings, normalize_name

__all__ = ["group_findings", "normalize_name"]
