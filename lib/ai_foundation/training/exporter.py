"""
Training Data Exporter — formats curated samples for fine-tuning.

Supports OpenAI fine-tuning JSONL format and DPO preference pair format.
Handles train/validation splitting and domain balance enforcement.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ExportStats(BaseModel):
    """Statistics from a data export run."""

    total_samples: int = 0
    train_samples: int = 0
    val_samples: int = 0
    domains: dict[str, int] = Field(default_factory=dict)
    output_path: str = ""


class TrainingExporter:
    """Exports curated samples into fine-tuning formats.

    Example::

        exporter = TrainingExporter(output_dir=Path("./training_data"))
        stats = exporter.export_openai_jsonl(
            samples=eligible_samples,
            task="intent_extraction",
            val_ratio=0.1,
        )
        print(f"Exported {stats.train_samples} train + {stats.val_samples} val")
    """

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def export_openai_jsonl(
        self,
        samples: list[dict[str, Any]],
        *,
        task: str = "intent_extraction",
        val_ratio: float = 0.1,
        max_samples: int | None = None,
        seed: int = 42,
    ) -> ExportStats:
        """Export samples in OpenAI fine-tuning JSONL format.

        Each line contains::

            {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}

        Args:
            samples: Curated samples from QualityFilter.
            task: Task identifier for filename.
            val_ratio: Fraction of samples for validation.
            max_samples: Cap on total samples.
            seed: Random seed for reproducible splitting.

        Returns:
            ``ExportStats`` with file paths and counts.
        """
        if max_samples:
            samples = samples[:max_samples]

        # Convert to OpenAI format
        formatted: list[dict[str, Any]] = []
        domain_counts: dict[str, int] = {}

        for sample in samples:
            messages = sample.get("messages", [])
            response = sample.get("response", "")

            if not messages or not response:
                continue

            # Build training example: all input messages + assistant response
            training_messages = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if content:
                    training_messages.append({"role": role, "content": content})

            training_messages.append({"role": "assistant", "content": response})

            formatted.append({"messages": training_messages})

            # Track domain for balance stats
            structured = sample.get("structured_output", {})
            data_types = structured.get("data_types", [])
            for dt in data_types[:1]:  # count primary domain
                domain = dt if isinstance(dt, str) else str(dt)
                domain_counts[domain] = domain_counts.get(domain, 0) + 1

        # Shuffle and split
        rng = random.Random(seed)
        rng.shuffle(formatted)

        split_idx = max(1, int(len(formatted) * (1 - val_ratio)))
        train = formatted[:split_idx]
        val = formatted[split_idx:]

        # Write files
        train_path = self._output_dir / f"{task}_train.jsonl"
        val_path = self._output_dir / f"{task}_val.jsonl"

        self._write_jsonl(train_path, train)
        self._write_jsonl(val_path, val)

        stats = ExportStats(
            total_samples=len(formatted),
            train_samples=len(train),
            val_samples=len(val),
            domains=domain_counts,
            output_path=str(self._output_dir),
        )
        logger.info(
            "Exported %d train + %d val to %s",
            len(train), len(val), self._output_dir,
        )
        return stats

    def export_preference_pairs(
        self,
        samples: list[dict[str, Any]],
        *,
        task: str = "response_generation",
    ) -> ExportStats:
        """Export preference pairs for DPO training.

        Pairs are formed from samples with different feedback scores
        on similar queries. Format::

            {"prompt": [...messages], "chosen": "good response", "rejected": "bad response"}

        Args:
            samples: Samples with ``feedback_score`` values.
            task: Task identifier for filename.
        """
        positive = [s for s in samples if (s.get("feedback_score") or 0) > 0.5]
        negative = [s for s in samples if s.get("feedback_score") is not None and s["feedback_score"] <= 0.5]

        pairs: list[dict[str, Any]] = []

        # Simple pairing: match by task type
        for pos in positive:
            for neg in negative:
                if pos.get("task") == neg.get("task"):
                    pairs.append({
                        "prompt": pos.get("messages", []),
                        "chosen": pos.get("response", ""),
                        "rejected": neg.get("response", ""),
                    })
                    negative.remove(neg)
                    break

        pair_path = self._output_dir / f"{task}_dpo_pairs.jsonl"
        self._write_jsonl(pair_path, pairs)

        return ExportStats(
            total_samples=len(pairs),
            train_samples=len(pairs),
            val_samples=0,
            output_path=str(pair_path),
        )

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
        """Write records as JSONL."""
        with open(path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
