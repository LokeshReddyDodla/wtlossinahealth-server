from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import Any, Optional

from .models import ConversationContext, IntentPlan, RetrievalPlan


def resolve_summary_window(
    intent,
    conversation_context: ConversationContext,
) -> Optional[tuple[date, date, str]]:
    if getattr(intent, "date_range", None) and getattr(intent.date_range, "start", None):
        start = intent.date_range.start.date()
        end_exclusive = intent.date_range.end.date()
        end = end_exclusive - timedelta(days=1) if end_exclusive > start else start
        return start, end, conversation_context.inherited_date_scope or "custom_range"

    scope = (conversation_context.inherited_date_scope or "").lower()
    today = datetime.now(UTC).date()
    if scope == "today":
        return today, today, "today"
    if scope == "yesterday":
        day = today - timedelta(days=1)
        return day, day, "yesterday"
    if scope == "last 4 days":
        return today - timedelta(days=3), today, "last_4_days"
    if scope == "this week":
        start = today - timedelta(days=today.weekday())
        return start, today, "this_week"
    if scope == "this month":
        start = today.replace(day=1)
        return start, today, "this_month"
    return None


async def build_patient_summary_payloads(
    mongo_store: Any,
    patient_id: Optional[str],
    intent,
    intent_plan: IntentPlan,
    retrieval_plan: RetrievalPlan,
    conversation_context: ConversationContext,
) -> list[dict]:
    if not mongo_store or not patient_id:
        return []

    wants_summary = retrieval_plan.use_patient_summary or any(
        domain.value in {"sleep", "vitals", "patient_summary"}
        for domain in intent_plan.domains
    )
    if not wants_summary:
        return []

    window = resolve_summary_window(intent, conversation_context)
    if not window:
        return []
    start_date, end_date, scope_label = window

    docs = await mongo_store.find_many(
        "patient_summaries",
        {
            "patient_id": patient_id,
            "metadata.report_type": "daily",
            "metadata.date_range.start": {
                "$gte": start_date.isoformat(),
                "$lte": end_date.isoformat() + "T23:59:59",
            },
        },
    )
    if not docs:
        return []

    docs = sorted(docs, key=lambda doc: doc.get("metadata", {}).get("date_range", {}).get("start", ""))
    if len(docs) == 1:
        doc = docs[0]
        summary_date = doc.get("metadata", {}).get("date_range", {}).get("start", "")[:10]
        return [
            {
                "data_type": "patient_summary",
                "summary_scope": scope_label,
                "summary_date": summary_date,
                "data_presence": doc.get("data_presence", {}),
                "glucose": doc.get("glucose"),
                "meals": doc.get("meals"),
                "activity": doc.get("activity"),
                "sleep": doc.get("sleep"),
                "vitals": doc.get("vitals"),
                "flags": doc.get("flags", []),
                "insights": doc.get("insights"),
                "source": "mongo_patient_summary",
            }
        ]

    return [aggregate_patient_summary_docs(docs, scope_label)]


def aggregate_patient_summary_docs(docs: list[dict], scope_label: str) -> dict:
    def avg(values: list[float]) -> Optional[float]:
        return round(mean(values), 2) if values else None

    def numeric_values(items: list[dict], key: str) -> list[float]:
        values = []
        for item in items:
            value = item.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    glucose_docs = [doc.get("glucose") or {} for doc in docs if doc.get("glucose")]
    meal_docs = [doc.get("meals") or {} for doc in docs if doc.get("meals")]
    activity_docs = [doc.get("activity") or {} for doc in docs if doc.get("activity")]
    sleep_docs = [doc.get("sleep") or {} for doc in docs if doc.get("sleep")]
    vitals_docs = [doc.get("vitals") or {} for doc in docs if doc.get("vitals")]

    aggregated_presence: dict[str, bool] = {}
    for doc in docs:
        for key, value in (doc.get("data_presence") or {}).items():
            aggregated_presence[key] = aggregated_presence.get(key, False) or bool(value)

    glucose = None
    if glucose_docs:
        glucose = {
            "avg_mgdl": avg(numeric_values(glucose_docs, "avg_mgdl")),
            "tir_pct": avg(numeric_values(glucose_docs, "tir_pct")),
            "hyper_event_count": int(sum(numeric_values(glucose_docs, "hyper_event_count"))),
            "hypo_event_count": int(sum(numeric_values(glucose_docs, "hypo_event_count"))),
        }

    meals = None
    if meal_docs:
        totals = [doc.get("nutrition_totals") or {} for doc in meal_docs]
        meals = {
            "meal_count": int(sum(numeric_values(meal_docs, "meal_count"))),
            "nutrition_totals": {
                "calories": avg(numeric_values(totals, "calories")),
                "protein_g": avg(numeric_values(totals, "protein_g")),
                "carbs_g": avg(numeric_values(totals, "carbs_g")),
                "fat_g": avg(numeric_values(totals, "fat_g")),
                "fiber_g": avg(numeric_values(totals, "fiber_g")),
            },
        }

    activity = None
    if activity_docs:
        activity = {
            "steps": int(sum(numeric_values(activity_docs, "steps"))),
            "active_minutes": avg(numeric_values(activity_docs, "active_minutes")),
            "longest_inactive_minutes": max(numeric_values(activity_docs, "longest_inactive_minutes"), default=0),
            "peak_activity_hour": activity_docs[-1].get("peak_activity_hour"),
        }

    sleep = None
    if sleep_docs:
        sleep = {
            "duration_hours": avg(numeric_values(sleep_docs, "duration_hours")),
            "efficiency_pct": avg(numeric_values(sleep_docs, "efficiency_pct")),
            "sleep_quality": sleep_docs[-1].get("sleep_quality"),
        }

    vitals = None
    if vitals_docs:
        vitals = {
            "weight_kg": avg(numeric_values(vitals_docs, "weight_kg")),
            "heart_rate_avg": avg(numeric_values(vitals_docs, "heart_rate_avg")),
            "spo2_avg": avg(numeric_values(vitals_docs, "spo2_avg")),
            "temperature_avg_c": avg(numeric_values(vitals_docs, "temperature_avg_c")),
            "a1c_latest": vitals_docs[-1].get("a1c_latest"),
            "blood_pressure_avg": vitals_docs[-1].get("blood_pressure_avg"),
        }

    flags: list[str] = []
    for doc in docs:
        for flag in doc.get("flags", []) or []:
            if flag not in flags:
                flags.append(flag)

    return {
        "data_type": "patient_summary",
        "summary_scope": scope_label,
        "summary_date": docs[-1].get("metadata", {}).get("date_range", {}).get("start", "")[:10],
        "summary_days": len(docs),
        "data_presence": aggregated_presence,
        "glucose": glucose,
        "meals": meals,
        "activity": activity,
        "sleep": sleep,
        "vitals": vitals,
        "flags": flags,
        "source": "mongo_patient_summary_range",
    }
