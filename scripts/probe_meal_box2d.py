"""Probe whether the meal extractor gets box_2d back from the model.

Runs the real MealExtractor (same gateway/model/prompt as production) on one
image URL and prints each item's box_2d + derived center_point. If box_2d is
null here, the model isn't emitting boxes — not a data/deploy problem.

Usage:
    python scripts/probe_meal_box2d.py "<image_url>"
"""

import asyncio
import sys
from datetime import datetime, timezone

from lib.ai_foundation.agents.meal_analysis.context_loader import MealAnalysisContext
from lib.dependencies.service_dependencies import get_meal_analysis_agent


async def probe(image_url: str) -> None:
    agent = get_meal_analysis_agent()
    context = MealAnalysisContext(
        patient_id="probe",
        local_now=datetime.now(timezone.utc),
    )
    extraction = await agent._extractor.extract(
        context=context,
        slot="lunch",
        image_urls=[image_url],
    )
    print(f"model returned {len(extraction.items)} items\n")
    for it in extraction.items:
        print(f"  {it.name!r:40}  box_2d={it.box_2d}  center_point={it.center_point}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(probe(sys.argv[1]))
