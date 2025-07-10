from datetime import datetime
import json
from typing import Any, List, Optional, cast

from lib.core.container import container
from lib.core.mongo_store import MongoStore


class CGMMetricsService:
    async def get_patients_with_time_above_range(
        self,
        health_facility_id: str,
        min_duration_minutes: int = 45,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[dict]:
        from lib.dependencies.service_dependencies import (
            get_cgm_report_collection,
        )

        match_query = cast(
            dict,
            {
                "overall.hyper_stats.hyper_events": {"$ne": []},
            },
        )

        if start_date:
            match_query["start_date"] = {"$gte": start_date}
        if end_date:
            match_query.setdefault("start_date", {}).update({"$lte": end_date})

        pipeline = [
            {"$match": match_query},
            {
                "$lookup": {
                    "from": "patients",
                    "localField": "patient_id",
                    "foreignField": "patient_id",
                    "as": "patient",
                }
            },
            {"$skip": offset},
            {"$limit": limit},
            # {
            #     "$project": {
            #         "_id": 1,
            #         "patient_id": 1,
            #         "start_date": 1,
            #         "hyper_stats.hyper_events": 1,
            #     }
            # },
        ]

        mongo = get_cgm_report_collection()
        results = await mongo.aggregate(pipeline).to_list(length=limit)  # type: ignore
        print("result count:", len(results))

        return results
