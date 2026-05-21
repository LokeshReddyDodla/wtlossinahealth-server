"""Backfill profile_completion.missing[] on every existing patient.

The manifest-based completion logic landed after most patients were already
created, so their profile_completion JSON has only the old
{is_complete, is_mandatory} shape — no missing[]. This script recomputes
profile_completion for every patient using the current manifest and writes
the fresh shape.

Idempotent: if the patient's profile_completion already matches what
_recompute_profile_completion would produce, no UPDATE is issued.

Usage:
    python scripts/backfill_profile_completion.py            # apply
    python scripts/backfill_profile_completion.py --dry-run  # report only

Inside Docker:
    docker compose exec api python scripts/backfill_profile_completion.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.future import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from lib.core.onboarding_requirements import (  # noqa: E402
    ONBOARDING_REQUIREMENTS,
    compute_section_status,
)
from lib.core.postgres_store import PostgresStore  # noqa: E402
from lib.models.patient import Patient  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("backfill_profile_completion")


def _recompute(patient) -> tuple[dict, bool]:
    """Mirror of PatientProfileService._recompute_profile_completion logic.

    Returns (new_profile_completion_dict, changed_vs_old).
    """
    old = patient.profile_completion or {}
    new: dict[str, dict] = {}
    for section, paths in ONBOARDING_REQUIREMENTS.items():
        is_complete, missing = compute_section_status(patient, paths)
        prev = old.get(section, {})
        new[section] = {
            "is_complete": is_complete,
            "is_mandatory": prev.get("is_mandatory", True),
            "missing": missing,
        }
    return new, new != old


async def run(dry_run: bool) -> None:
    store = PostgresStore()
    try:
        async with store.get_session() as session:
            stmt = select(Patient).options(
                selectinload(Patient.daily_activity),
                selectinload(Patient.alcohol_consumption),
                selectinload(Patient.smoking_habit),
                selectinload(Patient.sleep_habit),
                selectinload(Patient.eating_habit),
                selectinload(Patient.diabetic_history),
            )
            result = await session.execute(stmt)
            patients = result.scalars().all()

            total = len(patients)
            changed_count = 0
            section_completion_counts = {
                section: 0 for section in ONBOARDING_REQUIREMENTS
            }

            logger.info(f"─── Scanning {total} patients ───")
            for patient in patients:
                new_pc, changed = _recompute(patient)
                for section, info in new_pc.items():
                    if info["is_complete"]:
                        section_completion_counts[section] += 1
                if changed:
                    changed_count += 1
                    if not dry_run:
                        patient.profile_completion = new_pc
                        flag_modified(patient, "profile_completion")

            logger.info(f"  patients needing update: {changed_count}/{total}")
            logger.info("─── Section completion across all patients ───")
            for section, count in section_completion_counts.items():
                pct = (count / total * 100) if total else 0
                logger.info(
                    f"  {section}: {count}/{total} complete ({pct:.1f}%)"
                )

            if dry_run:
                logger.info("Dry-run mode — no UPDATEs applied.")
            else:
                await session.commit()
                logger.info(f"✅ Committed {changed_count} profile_completion updates.")
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show counts without writing.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
