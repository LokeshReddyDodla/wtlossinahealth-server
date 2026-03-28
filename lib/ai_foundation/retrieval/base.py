"""
Shared Retrieval Protocol — defines the interface for data retrieval
from any source (Qdrant, etc.).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RetrievalRequest(BaseModel):
    """Common retrieval request accepted by all retrievers."""

    query: str = Field(description="Natural language query or search text.")
    patient_ids: list[str] = Field(
        default_factory=list,
        description="Patient IDs to filter results by.",
    )
    data_types: list[str] = Field(
        default_factory=list,
        description="Health data types to retrieve, e.g. ['meal', 'cgm_range_stats'].",
    )
    date_start: str | None = Field(
        default=None,
        description="Inclusive start date (ISO 8601).",
    )
    date_end: str | None = Field(
        default=None,
        description="Exclusive end date (ISO 8601).",
    )
    limit: int = Field(
        default=24,
        gt=0,
        description="Maximum number of results to return.",
    )
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional source-specific filters.",
    )


class RetrievalResult(BaseModel):
    """A single item returned by a retriever."""

    payload: dict[str, Any] = Field(description="The retrieved data payload.")
    source: str = Field(
        description="Which retriever produced this result, e.g. 'qdrant', 'mongo_report'.",
    )
    score: float | None = Field(
        default=None,
        description="Relevance or similarity score (0.0-1.0). None for exact-match sources.",
    )
    data_type: str | None = Field(
        default=None,
        description="Health data type of this result.",
    )


class CompositeResult(BaseModel):
    """Aggregated result from multiple retrievers run in parallel."""

    items: list[RetrievalResult] = Field(default_factory=list)
    executed_sources: list[str] = Field(
        default_factory=list,
        description="Sources that completed successfully.",
    )
    degraded_sources: list[str] = Field(
        default_factory=list,
        description="Sources that timed out or errored.",
    )
    warnings: list[str] = Field(default_factory=list)
    best_score: float | None = Field(
        default=None,
        description="Highest relevance score across all results.",
    )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Retriever(Protocol):
    """Protocol for a single data retriever.

    Implementations must be async and return a list of RetrievalResult.
    """

    name: str

    async def retrieve(self, request: RetrievalRequest) -> list[RetrievalResult]:
        """Execute the retrieval and return results."""
        ...
