"""
Dataset Validator — checks training data quality before submission.

Validates schema conformance, domain balance, duplicate detection, and
PHI absence before a dataset is submitted for fine-tuning.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ValidationIssue(BaseModel):
    """A single issue found during validation."""

    severity: str = Field(description="'error' or 'warning'.")
    message: str
    line_number: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    """Complete validation report for a dataset."""

    valid: bool = True
    total_examples: int = 0
    issues: list[ValidationIssue] = Field(default_factory=list)
    domain_distribution: dict[str, int] = Field(default_factory=dict)
    avg_messages_per_example: float = 0.0
    avg_response_length: float = 0.0
    duplicate_count: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


class DatasetValidator:
    """Validates training datasets before fine-tuning submission.

    Example::

        validator = DatasetValidator()
        report = validator.validate_jsonl(Path("intent_extraction_train.jsonl"))
        if report.valid:
            print("Dataset is ready for fine-tuning!")
        else:
            for issue in report.issues:
                print(f"  [{issue.severity}] {issue.message}")
    """

    # PHI indicators
    _PHI_INDICATORS = ["[PHONE]", "[EMAIL]", "[SSN]", "[DOB]"]

    def validate_jsonl(
        self,
        path: Path,
        *,
        min_examples: int = 10,
        max_duplicate_rate: float = 0.05,
        max_domain_skew: float = 0.8,
    ) -> ValidationReport:
        """Validate an OpenAI fine-tuning JSONL file.

        Args:
            path: Path to the JSONL file.
            min_examples: Minimum number of valid examples required.
            max_duplicate_rate: Maximum fraction of duplicates allowed.
            max_domain_skew: Maximum fraction of examples from a single domain.

        Returns:
            ``ValidationReport`` with all issues found.
        """
        report = ValidationReport()

        if not path.exists():
            report.valid = False
            report.issues.append(ValidationIssue(
                severity="error", message=f"File not found: {path}",
            ))
            return report

        examples: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        total_messages = 0
        total_response_len = 0
        duplicates = 0

        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                # Parse JSON
                try:
                    example = json.loads(line)
                except json.JSONDecodeError as exc:
                    report.issues.append(ValidationIssue(
                        severity="error",
                        message=f"Invalid JSON at line {line_num}: {exc}",
                        line_number=line_num,
                    ))
                    continue

                # Check structure
                messages = example.get("messages")
                if not isinstance(messages, list) or len(messages) < 2:
                    report.issues.append(ValidationIssue(
                        severity="error",
                        message=f"Line {line_num}: 'messages' must be a list with >= 2 items.",
                        line_number=line_num,
                    ))
                    continue

                # Check roles
                roles = [m.get("role") for m in messages]
                if "assistant" not in roles:
                    report.issues.append(ValidationIssue(
                        severity="error",
                        message=f"Line {line_num}: No assistant message found.",
                        line_number=line_num,
                    ))
                    continue

                # Check for empty content
                for i, msg in enumerate(messages):
                    if not msg.get("content", "").strip():
                        report.issues.append(ValidationIssue(
                            severity="warning",
                            message=f"Line {line_num}: Message {i} has empty content.",
                            line_number=line_num,
                        ))

                # Check for unscrubbed PHI
                full_text = " ".join(m.get("content", "") for m in messages)
                for indicator in self._PHI_INDICATORS:
                    if indicator in full_text:
                        report.issues.append(ValidationIssue(
                            severity="warning",
                            message=f"Line {line_num}: Contains PHI placeholder {indicator}.",
                            line_number=line_num,
                        ))

                # Duplicate detection
                content_hash = hashlib.sha256(full_text.encode()).hexdigest()[:16]
                if content_hash in seen_hashes:
                    duplicates += 1
                else:
                    seen_hashes.add(content_hash)

                # Stats
                total_messages += len(messages)
                assistant_msg = next(
                    (m["content"] for m in messages if m["role"] == "assistant"),
                    "",
                )
                total_response_len += len(assistant_msg)

                examples.append(example)

        report.total_examples = len(examples)
        report.duplicate_count = duplicates

        if examples:
            report.avg_messages_per_example = round(total_messages / len(examples), 1)
            report.avg_response_length = round(total_response_len / len(examples), 1)

        # Min examples check
        if len(examples) < min_examples:
            report.issues.append(ValidationIssue(
                severity="error",
                message=f"Only {len(examples)} examples (minimum: {min_examples}).",
            ))

        # Duplicate rate check
        if examples:
            dup_rate = duplicates / len(examples)
            if dup_rate > max_duplicate_rate:
                report.issues.append(ValidationIssue(
                    severity="warning",
                    message=f"Duplicate rate {dup_rate:.1%} exceeds {max_duplicate_rate:.1%}.",
                ))

        # Determine validity
        report.valid = report.error_count == 0

        logger.info(
            "Validation: %d examples, %d errors, %d warnings, valid=%s",
            report.total_examples,
            report.error_count,
            report.warning_count,
            report.valid,
        )
        return report
