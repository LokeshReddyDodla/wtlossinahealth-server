"""
Composite Retriever — runs multiple retrievers in parallel with individual
timeouts and graceful degradation.

This is the primary retrieval interface that agents use. It wraps multiple
Retriever implementations (Qdrant, MongoDB, patient summaries) and runs
them concurrently, collecting results from all that succeed within their
timeout window.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .base import CompositeResult, Retriever, RetrievalRequest, RetrievalResult

logger = logging.getLogger(__name__)


class _RegisteredRetriever:
    """Internal wrapper holding a retriever and its configuration."""

    __slots__ = ("retriever", "timeout_seconds", "required")

    def __init__(
        self,
        retriever: Retriever,
        timeout_seconds: float,
        required: bool,
    ) -> None:
        self.retriever = retriever
        self.timeout_seconds = timeout_seconds
        self.required = required


class CompositeRetriever:
    """Runs multiple retrievers in parallel with timeouts and degradation.

    Registered retrievers are categorised as **required** or **optional**:
    - Required: failure raises an error (the result is unusable without this data).
    - Optional: failure degrades gracefully (results are still returned, with a warning).

    Example::

        composite = CompositeRetriever()
        composite.register("mongo_reports", mongo_retriever, timeout_seconds=5.0, required=True)
        composite.register("qdrant", qdrant_retriever, timeout_seconds=8.0, required=False)
        composite.register("patient_summary", summary_retriever, timeout_seconds=5.0, required=False)

        result = await composite.retrieve(
            RetrievalRequest(query="glucose after dinner", patient_ids=["p123"]),
            sources=["mongo_reports", "qdrant"],  # optionally limit which sources to use
        )
    """

    def __init__(self) -> None:
        self._retrievers: dict[str, _RegisteredRetriever] = {}

    def register(
        self,
        name: str,
        retriever: Retriever,
        *,
        timeout_seconds: float = 8.0,
        required: bool = False,
    ) -> None:
        """Register a retriever with its timeout and required/optional flag."""
        self._retrievers[name] = _RegisteredRetriever(
            retriever=retriever,
            timeout_seconds=timeout_seconds,
            required=required,
        )
        logger.debug(
            "Registered retriever %r (timeout=%.1fs, required=%s)",
            name,
            timeout_seconds,
            required,
        )

    async def retrieve(
        self,
        request: RetrievalRequest,
        *,
        sources: list[str] | None = None,
    ) -> CompositeResult:
        """Run retrievers in parallel and collect results.

        Args:
            request: The retrieval request.
            sources: Optional list of retriever names to use. If None, all
                registered retrievers are used.

        Returns:
            ``CompositeResult`` with items from all successful retrievers.

        Raises:
            RuntimeError: If a **required** retriever fails.
        """
        target_names = sources or list(self._retrievers.keys())
        targets = {
            name: self._retrievers[name]
            for name in target_names
            if name in self._retrievers
        }

        if not targets:
            return CompositeResult()

        # Run all retrievers concurrently
        tasks = {
            name: asyncio.create_task(
                self._run_one(name, reg, request),
                name=f"retrieve:{name}",
            )
            for name, reg in targets.items()
        }

        results: dict[str, list[RetrievalResult] | Exception] = {}
        for name, task in tasks.items():
            try:
                results[name] = await task
            except Exception as exc:
                results[name] = exc

        # Assemble composite result
        all_items: list[RetrievalResult] = []
        executed: list[str] = []
        degraded: list[str] = []
        warnings: list[str] = []

        for name, result in results.items():
            reg = targets[name]
            if isinstance(result, Exception):
                if reg.required:
                    raise RuntimeError(
                        f"Required retriever {name!r} failed: {result}"
                    ) from result
                degraded.append(name)
                warnings.append(f"Retriever {name!r} failed: {result}")
                logger.warning("Optional retriever %r failed: %s", name, result)
            else:
                all_items.extend(result)
                executed.append(name)

        best_score = max(
            (r.score for r in all_items if r.score is not None),
            default=None,
        )

        return CompositeResult(
            items=all_items,
            executed_sources=executed,
            degraded_sources=degraded,
            warnings=warnings,
            best_score=best_score,
        )

    async def _run_one(
        self,
        name: str,
        reg: _RegisteredRetriever,
        request: RetrievalRequest,
    ) -> list[RetrievalResult]:
        """Run a single retriever with its configured timeout."""
        try:
            return await asyncio.wait_for(
                reg.retriever.retrieve(request),
                timeout=reg.timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Retriever {name!r} timed out after {reg.timeout_seconds}s"
            )

    def list_sources(self) -> list[dict[str, Any]]:
        """List all registered retrievers with their configuration."""
        return [
            {
                "name": name,
                "timeout_seconds": reg.timeout_seconds,
                "required": reg.required,
            }
            for name, reg in self._retrievers.items()
        ]

    def __contains__(self, name: str) -> bool:
        return name in self._retrievers

    def __repr__(self) -> str:
        sources = list(self._retrievers.keys())
        return f"CompositeRetriever(sources={sources})"
