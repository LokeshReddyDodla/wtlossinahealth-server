from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

from .models import ConversationContext, DomainName, IntentPlan


def resolve_report_window(
    intent,
    conversation_context: ConversationContext,
) -> Optional[tuple[date, date]]:
    if getattr(intent, "date_range", None) and getattr(intent.date_range, "start", None):
        start = intent.date_range.start.date()
        end_exclusive = intent.date_range.end.date()
        end = end_exclusive - timedelta(days=1) if end_exclusive > start else start
        return start, end

    scope = (conversation_context.inherited_date_scope or "").lower()
    today = datetime.now(UTC).date()
    if scope == "today":
        return today, today
    if scope == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if scope == "last 4 days":
        return today - timedelta(days=3), today
    if scope in {"this week", "last 7 days"}:
        start = today - timedelta(days=today.weekday()) if scope == "this week" else today - timedelta(days=6)
        return start, today
    if scope == "this month":
        return today.replace(day=1), today
    return None


class MongoReportFetcher:
    COLLECTION_BY_DOMAIN = {
        DomainName.MEAL: "meal_reports",
        DomainName.CGM: "cgm_reports",
        DomainName.FITNESS: "fitness_reports",
        DomainName.SLEEP: "sleep_reports",
    }

    async def fetch(
        self,
        *,
        mongo_store: Optional["MongoStore"],
        patient_id: Optional[str],
        intent,
        intent_plan: IntentPlan,
        conversation_context: ConversationContext,
    ) -> list[dict]:
        if not mongo_store or not patient_id:
            return []

        window = resolve_report_window(intent, conversation_context)
        if not window:
            return []
        start_date, end_date = window

        payloads: list[dict] = []
        for domain in intent_plan.domains:
            collection_name = self.COLLECTION_BY_DOMAIN.get(domain)
            if not collection_name:
                continue
            docs = await mongo_store.find_many(
                collection_name,
                self._build_query(domain, patient_id, start_date, end_date),
            )
            payloads.extend(self._normalize_docs(domain, docs))

        return payloads

    def _build_query(
        self,
        domain: DomainName,
        patient_id: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        if domain == DomainName.MEAL:
            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()
            return {
                "patient_id": patient_id,
                "report_type": "daily",
                "$or": [
                    {"date": {"$gte": start_iso, "$lte": end_iso}},
                    {
                        "metadata.date_range.start": {
                            "$gte": start_iso,
                            "$lte": end_iso + "T23:59:59",
                        }
                    },
                ],
            }

        start_iso = datetime.combine(start_date, datetime.min.time()).isoformat()
        end_iso = datetime.combine(end_date, datetime.max.time()).replace(microsecond=0).isoformat()
        return {
            "patient_id": patient_id,
            "metadata.report_type": "daily",
            "metadata.date_range.start": {"$gte": start_iso},
            "metadata.date_range.end": {"$lte": end_iso},
        }

    def _normalize_docs(self, domain: DomainName, docs: list[dict]) -> list[dict]:
        if domain == DomainName.MEAL:
            return self._normalize_meal_reports(docs)
        if domain == DomainName.FITNESS:
            return self._normalize_fitness_reports(docs)
        if domain == DomainName.CGM:
            return self._normalize_cgm_reports(docs)
        if domain == DomainName.SLEEP:
            return self._normalize_sleep_reports(docs)
        return []

    @staticmethod
    def _normalize_meal_reports(docs: list[dict]) -> list[dict]:
        payloads: list[dict] = []
        for doc in docs:
            report_date = doc.get("date") or (doc.get("metadata", {}).get("date_range", {}).get("start", "")[:10])
            meals = doc.get("meals") or []
            for meal in meals:
                payloads.append(
                    {
                        "data_type": "meal",
                        "date": report_date,
                        "meal_type": meal.get("meal_type") or meal.get("type"),
                        "meal_name": meal.get("meal_name") or meal.get("name"),
                        "time": meal.get("time"),
                        "nutrition": meal.get("nutrition") or meal.get("macros") or {},
                        "source": "mongo_report",
                    }
                )
        return payloads

    @staticmethod
    def _normalize_fitness_reports(docs: list[dict]) -> list[dict]:
        payloads: list[dict] = []
        for doc in docs:
            peak = doc.get("peak_activity_time") or {}
            hour = peak.get("hour")
            try:
                peak_hour = int(str(hour).split(":")[0]) if hour is not None else None
            except Exception:
                peak_hour = None
            payloads.append(
                {
                    "data_type": "fitness_overview",
                    "steps": doc.get("steps"),
                    "active_duration": doc.get("active_duration"),
                    "peak_hour": peak_hour,
                    "source": "mongo_report",
                }
            )
        return payloads

    @staticmethod
    def _normalize_cgm_reports(docs: list[dict]) -> list[dict]:
        payloads: list[dict] = []
        for doc in docs:
            summary_stats = doc.get("cgm_summary_stats") or {}
            range_stats = doc.get("cgm_range_stats") or {}
            if summary_stats:
                payloads.append(
                    {
                        "data_type": "cgm_summary_stats",
                        "data": {
                            "average_glucose_mgdl": summary_stats.get("average_glucose_mgdl"),
                            "gmi": summary_stats.get("gmi"),
                        },
                        "source": "mongo_report",
                    }
                )
            if range_stats:
                payloads.append(
                    {
                        "data_type": "cgm_range_stats",
                        "data": {
                            "in_target_70_180_percent": range_stats.get("in_target_70_180_percent"),
                        },
                        "source": "mongo_report",
                    }
                )
        return payloads

    @staticmethod
    def _normalize_sleep_reports(docs: list[dict]) -> list[dict]:
        payloads: list[dict] = []
        for doc in docs:
            duration = doc.get("duration") or {}
            quality = doc.get("quality") or {}
            avg_minutes = (
                duration.get("per_day_average_duration")
                or duration.get("average_duration")
                or duration.get("total_duration")
            )
            payloads.append(
                {
                    "data_type": "sleep_report",
                    "duration_hours": round(float(avg_minutes) / 60, 2)
                    if isinstance(avg_minutes, (int, float))
                    else None,
                    "efficiency_pct": quality.get("sleep_efficiency"),
                    "sleep_quality": quality.get("sleep_quality"),
                    "source": "mongo_report",
                }
            )
        return payloads
