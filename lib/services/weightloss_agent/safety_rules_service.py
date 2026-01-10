"""Table-driven safety rules evaluator for the weightloss agent."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from decouple import config

from lib.services.weightloss_agent.analytics_service import AnalyticsService


class SafetyRulesService:
    SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}

    def __init__(
        self,
        analytics_service: AnalyticsService,
        csv_path: Optional[Path] = None,
    ) -> None:
        self.analytics_service = analytics_service
        default_path = Path(__file__).resolve().parent / "data" / "safety_rules.csv"
        self.csv_path = csv_path or default_path
        self._rules = self._load_rules()
        self.is_enabled = (
            str(config("WEIGHTLOSS_SAFETY_RULES_ENABLED", default="true"))
            .strip()
            .lower()
            not in ("0", "false", "no", "off")
        )

    def _load_rules(self) -> List[Dict[str, Any]]:
        rules: List[Dict[str, Any]] = []
        if not self.csv_path.exists():
            return rules
        with self.csv_path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, skipinitialspace=True)
            for row in reader:
                trigger = json.loads(row["trigger"].strip())
                action = json.loads(row["action"].strip())
                rules.append(
                    {
                        "rule_id": row["rule_id"],
                        "trigger": trigger,
                        "action": action,
                        "rationale_source_id": row["rationale_source_id"],
                        "severity": row.get("severity", "medium"),
                        "mutually_exclusive_with": self._parse_mutually_exclusive(
                            row.get("mutually_exclusive_with")
                        ),
                        "version": row.get("version"),
                    }
                )
        return rules

    def _parse_mutually_exclusive(self, value: Optional[str]) -> List[str]:
        if not value:
            return []
        raw = value.strip()
        separators = ["|", ",", ";"]
        tokens = [raw]
        for sep in separators:
            if sep in raw:
                tokens = [item.strip() for item in raw.split(sep) if item.strip()]
                break
        return tokens

    async def evaluate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_enabled:
            return {
                "contraindications": [],
                "intensity_caps": [],
                "rationale_ids": [],
            }

        triggered = []
        for rule in self._rules:
            if self._rule_matches(rule["trigger"], context):
                triggered.append(rule)

        triggered = self._resolve_mutual_exclusion(triggered)

        contraindications: List[Dict[str, Any]] = []
        intensity_caps: List[Dict[str, Any]] = []
        rationale_ids: List[str] = []

        for rule in triggered:
            action = rule["action"]
            if action.get("type") == "contraindication":
                contraindications.append(
                    {
                        **action,
                        "rule_id": rule["rule_id"],
                        "severity": rule["severity"],
                        "rationale_source_id": rule["rationale_source_id"],
                    }
                )
            elif action.get("type") == "intensity_cap":
                intensity_caps.append(
                    {
                        **action,
                        "rule_id": rule["rule_id"],
                        "severity": rule["severity"],
                        "rationale_source_id": rule["rationale_source_id"],
                    }
                )
            rationale_ids.append(rule["rationale_source_id"])

        if triggered:
            await self.analytics_service.emit_event(
                event_type="safety_flag",
                user_id=context.get("user_id"),
                payload={
                    "rule_ids": [rule["rule_id"] for rule in triggered],
                    "severity": [rule["severity"] for rule in triggered],
                },
                severity="warning",
            )

        return {
            "contraindications": contraindications,
            "intensity_caps": intensity_caps,
            "rationale_ids": list({rid for rid in rationale_ids if rid}),
        }

    def _rule_matches(self, trigger: Dict[str, Any], context: Dict[str, Any]) -> bool:
        clauses = trigger.get("all") or []
        for clause in clauses:
            source = clause.get("source")
            field = clause.get("field")
            operator = clause.get("operator")
            expected = clause.get("value")
            actual = self._resolve_value(context, source, field)
            if not self._compare(operator, actual, expected):
                return False
        return True

    def _resolve_value(
        self, context: Dict[str, Any], source: Optional[str], field: Optional[str]
    ) -> Any:
        if not source:
            return None
        bucket = context.get(source, {})
        if not isinstance(bucket, dict) or not field:
            return bucket if field is None else None

        if field in bucket:
            return bucket[field]

        for value in bucket.values():
            if isinstance(value, dict) and field in value:
                return value[field]

        return None

    def _compare(self, operator: str, actual: Any, expected: Any) -> bool:
        if operator in (">=", "gte"):
            return actual is not None and actual >= expected
        if operator in ("<=", "lte"):
            return actual is not None and actual <= expected
        if operator in (">", "gt"):
            return actual is not None and actual > expected
        if operator in ("<", "lt"):
            return actual is not None and actual < expected
        if operator in ("=", "eq"):
            return actual == expected
        if operator == "contains":
            if isinstance(actual, list):
                return expected in actual
            if isinstance(actual, str):
                return str(expected) in actual
        return False

    def _resolve_mutual_exclusion(
        self, rules: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        by_id = {rule["rule_id"]: rule for rule in rules}
        for rule in list(rules):
            conflicts = rule.get("mutually_exclusive_with", [])
            for conflict_id in conflicts:
                conflict = by_id.get(conflict_id)
                if not conflict:
                    continue
                if (
                    self.SEVERITY_ORDER.get(conflict["severity"], 0)
                    > self.SEVERITY_ORDER.get(rule["severity"], 0)
                ):
                    rules.remove(rule)
                    break
                else:
                    rules.remove(conflict)
        return rules
