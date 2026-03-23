from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Optional

from .models import AnalysisSnapshot, DomainName, IntentPlan, RetrievalPlan


class StructuredAnalyzer:
    @classmethod
    def build_snapshot(
        cls,
        raw_points: Iterable[dict],
        intent_plan: IntentPlan,
        retrieval_plan: RetrievalPlan,
        patient_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> AnalysisSnapshot:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for payload in raw_points:
            grouped[payload.get("data_type", "unknown")].append(payload)

        summary: dict[str, Any] = {
            "result_count": sum(len(items) for items in grouped.values()),
            "data_types": {key: len(items) for key, items in grouped.items()},
            "response_mode": intent_plan.response_mode.value,
            "playbooks": retrieval_plan.playbooks,
        }
        highlights: list[str] = []

        meal_items = grouped.get("meal", [])
        if meal_items:
            calories = sum((item.get("nutrition") or {}).get("calories", 0) or 0 for item in meal_items)
            proteins = sum((item.get("nutrition") or {}).get("proteins", 0) or 0 for item in meal_items)
            summary["meals"] = {
                "count": len(meal_items),
                "total_calories": calories,
                "total_protein_g": proteins,
                "meal_types": [item.get("meal_type") for item in meal_items if item.get("meal_type")],
                "meal_names": [item.get("meal_name") for item in meal_items if item.get("meal_name")][:8],
            }
            highlights.append(f"Meals found: {len(meal_items)}")

        fitness_items = grouped.get("fitness_overview", [])
        if fitness_items:
            latest = fitness_items[0]
            summary["fitness"] = {
                "count": len(fitness_items),
                "steps": latest.get("steps"),
                "active_duration": latest.get("active_duration"),
                "peak_hour": latest.get("peak_hour"),
            }
            if latest.get("steps") is not None:
                highlights.append(f"Latest steps: {latest.get('steps')}")

        cgm_summary_items = grouped.get("cgm_summary_stats", [])
        cgm_range_items = grouped.get("cgm_range_stats", [])
        if cgm_summary_items or cgm_range_items:
            latest_summary = cgm_summary_items[0] if cgm_summary_items else {}
            latest_range = cgm_range_items[0] if cgm_range_items else {}
            summary["cgm"] = {
                "summary_count": len(cgm_summary_items),
                "range_count": len(cgm_range_items),
                "average_glucose_mgdl": (latest_summary.get("data") or {}).get("average_glucose_mgdl"),
                "gmi": (latest_summary.get("data") or {}).get("gmi"),
                "tir_percent": (latest_range.get("data") or {}).get("in_target_70_180_percent"),
            }
            if summary["cgm"].get("average_glucose_mgdl") is not None:
                highlights.append(
                    f"Average glucose: {summary['cgm']['average_glucose_mgdl']} mg/dL"
                )

        smbg_items = grouped.get("smbg", [])
        if smbg_items:
            summary["smbg"] = {
                "count": len(smbg_items),
                "latest_glucose_mgdl": smbg_items[0].get("glucose_mgdl"),
                "reading_types": [item.get("reading_type") for item in smbg_items if item.get("reading_type")][:6],
            }
            highlights.append(f"SMBG readings: {len(smbg_items)}")

        profile_items = grouped.get("profile", [])
        if profile_items:
            profile = profile_items[0]
            summary["profile"] = {
                "age": profile.get("age"),
                "gender": profile.get("gender"),
                "weight": profile.get("weight"),
                "bmi": profile.get("bmi"),
                "activity_level": profile.get("activity_level"),
                "diet_preference": profile.get("diet_preference"),
            }

        document_items = grouped.get("patient_document", [])
        if document_items:
            summary["documents"] = {
                "count": len(document_items),
                "document_types": sorted({item.get("document_type") for item in document_items if item.get("document_type")}),
            }
            highlights.append(f"Documents found: {len(document_items)}")

        patient_summary_items = grouped.get("patient_summary", [])
        if patient_summary_items:
            latest_summary = patient_summary_items[0]
            summary["patient_summary"] = {
                "count": len(patient_summary_items),
                "summary_date": latest_summary.get("summary_date"),
                "data_presence": latest_summary.get("data_presence", {}),
                "flags": latest_summary.get("flags", []),
            }
            if latest_summary.get("sleep") and "sleep" not in summary:
                summary["sleep"] = latest_summary.get("sleep")
            if latest_summary.get("vitals") and "vitals" not in summary:
                summary["vitals"] = latest_summary.get("vitals")
            if latest_summary.get("activity") and "fitness" not in summary:
                activity = latest_summary.get("activity") or {}
                summary["fitness"] = {
                    "count": 1,
                    "steps": activity.get("steps"),
                    "active_duration": activity.get("active_minutes"),
                    "peak_hour": activity.get("peak_activity_hour"),
                }
            highlights.append(
                f"Patient summary available for {latest_summary.get('summary_date')}"
            )

        sleep_report_items = grouped.get("sleep_report", [])
        if sleep_report_items and "sleep" not in summary:
            latest_sleep = sleep_report_items[0]
            summary["sleep"] = {
                "count": len(sleep_report_items),
                "duration_hours": latest_sleep.get("duration_hours"),
                "efficiency_pct": latest_sleep.get("efficiency_pct"),
                "sleep_quality": latest_sleep.get("sleep_quality"),
            }
            if latest_sleep.get("duration_hours") is not None:
                highlights.append(
                    f"Sleep duration: {latest_sleep.get('duration_hours')} hours"
                )

        return AnalysisSnapshot(
            patient_id=patient_id,
            thread_id=thread_id,
            domains=intent_plan.domains,
            response_mode=intent_plan.response_mode,
            summary=summary,
            highlights=highlights,
            evidence={"grouped_counts": summary.get("data_types", {})},
        )
