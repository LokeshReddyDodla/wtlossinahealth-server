"""
Training Runner — submits and monitors fine-tuning jobs.

Supports the OpenAI Fine-Tuning API. Handles file upload, job creation,
status polling, and result retrieval.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class TrainingJobStatus(str, Enum):
    """Status of a fine-tuning job."""

    PENDING = "pending"
    VALIDATING = "validating_files"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TrainingJobConfig(BaseModel):
    """Configuration for a fine-tuning job."""

    model_config = {"protected_namespaces": ()}

    base_model: str = Field(description="Base model to fine-tune, e.g. 'gpt-4.1-mini'.")
    training_file: str = Field(description="Path to training JSONL file.")
    validation_file: str | None = Field(
        default=None,
        description="Path to validation JSONL file.",
    )
    n_epochs: int = Field(default=3, ge=1, le=10)
    suffix: str = Field(
        default="health",
        description="Suffix appended to the fine-tuned model name.",
    )
    hyperparameters: dict[str, Any] = Field(default_factory=dict)


class TrainingJobResult(BaseModel):
    """Result from a completed fine-tuning job."""

    model_config = {"protected_namespaces": ()}

    job_id: str
    status: TrainingJobStatus
    fine_tuned_model: str | None = Field(
        default=None,
        description="The new model ID if training succeeded.",
    )
    base_model: str = ""
    training_file_id: str = ""
    trained_tokens: int | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None


class TrainingRunner:
    """Manages fine-tuning job lifecycle via the OpenAI API.

    Example::

        runner = TrainingRunner(api_key="sk-...")

        # Upload and submit
        result = await runner.submit_job(TrainingJobConfig(
            base_model="gpt-4.1-mini",
            training_file="./training_data/intent_extraction_train.jsonl",
            validation_file="./training_data/intent_extraction_val.jsonl",
            n_epochs=3,
            suffix="health-intent-v1",
        ))

        # Check status
        status = await runner.get_status(result.job_id)
        print(f"Job {result.job_id}: {status.status.value}")

        # When done
        if status.fine_tuned_model:
            print(f"New model: {status.fine_tuned_model}")
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazily create the OpenAI client."""
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key or "")
        return self._client

    async def submit_job(self, config: TrainingJobConfig) -> TrainingJobResult:
        """Upload training files and submit a fine-tuning job.

        This is a blocking operation (file upload + job creation).
        """
        import asyncio
        return await asyncio.to_thread(self._submit_sync, config)

    def _submit_sync(self, config: TrainingJobConfig) -> TrainingJobResult:
        """Synchronous job submission."""
        client = self._get_client()

        # Upload training file
        logger.info("Uploading training file: %s", config.training_file)
        with open(config.training_file, "rb") as f:
            train_file = client.files.create(file=f, purpose="fine-tune")

        # Upload validation file if provided
        val_file_id = None
        if config.validation_file:
            logger.info("Uploading validation file: %s", config.validation_file)
            with open(config.validation_file, "rb") as f:
                val_file = client.files.create(file=f, purpose="fine-tune")
                val_file_id = val_file.id

        # Create fine-tuning job
        create_params: dict[str, Any] = {
            "training_file": train_file.id,
            "model": config.base_model,
            "suffix": config.suffix,
            "hyperparameters": {"n_epochs": config.n_epochs, **config.hyperparameters},
        }
        if val_file_id:
            create_params["validation_file"] = val_file_id

        logger.info("Submitting fine-tuning job (model=%s, suffix=%s)", config.base_model, config.suffix)
        job = client.fine_tuning.jobs.create(**create_params)

        return TrainingJobResult(
            job_id=job.id,
            status=TrainingJobStatus(job.status),
            base_model=config.base_model,
            training_file_id=train_file.id,
        )

    async def get_status(self, job_id: str) -> TrainingJobResult:
        """Poll the status of a fine-tuning job."""
        import asyncio
        return await asyncio.to_thread(self._get_status_sync, job_id)

    def _get_status_sync(self, job_id: str) -> TrainingJobResult:
        """Synchronous status retrieval."""
        client = self._get_client()
        job = client.fine_tuning.jobs.retrieve(job_id)

        return TrainingJobResult(
            job_id=job.id,
            status=TrainingJobStatus(job.status),
            fine_tuned_model=job.fine_tuned_model,
            base_model=job.model,
            training_file_id=job.training_file,
            trained_tokens=getattr(job, "trained_tokens", None),
            error=str(job.error) if job.error else None,
            finished_at=datetime.fromtimestamp(job.finished_at, tz=timezone.utc) if job.finished_at else None,
        )

    async def cancel_job(self, job_id: str) -> TrainingJobResult:
        """Cancel a running fine-tuning job."""
        import asyncio
        return await asyncio.to_thread(self._cancel_sync, job_id)

    def _cancel_sync(self, job_id: str) -> TrainingJobResult:
        client = self._get_client()
        job = client.fine_tuning.jobs.cancel(job_id)
        return TrainingJobResult(
            job_id=job.id,
            status=TrainingJobStatus(job.status),
            base_model=job.model,
        )

    async def list_jobs(self, *, limit: int = 10) -> list[TrainingJobResult]:
        """List recent fine-tuning jobs."""
        import asyncio
        return await asyncio.to_thread(self._list_sync, limit)

    def _list_sync(self, limit: int) -> list[TrainingJobResult]:
        client = self._get_client()
        jobs = client.fine_tuning.jobs.list(limit=limit)
        return [
            TrainingJobResult(
                job_id=j.id,
                status=TrainingJobStatus(j.status),
                fine_tuned_model=j.fine_tuned_model,
                base_model=j.model,
                training_file_id=j.training_file,
            )
            for j in jobs.data
        ]
