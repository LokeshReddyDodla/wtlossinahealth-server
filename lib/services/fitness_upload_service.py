from datetime import datetime
from dateutil.parser import parse
from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lib.core.clickhouse_store import canonical_vital_type
from lib.core.postgres_store import PostgresStore
from lib.derived import DataDomain, dates_between, mark_dirty
from lib.models.patient_smbg import PatientSMBG
from lib.workers.tasks.vitals.enqueue import enqueue_generate_vital_vector_async
from lib.utils.postgres_session_decorator import with_postgres_session
from rest_server.patients.fitness.api_schema import FitnessDataRequest
from sqlalchemy.ext.asyncio import AsyncSession

_SLEEP_FIELDS = ("sleep_in_bed", "sleep_deep", "sleep_light", "sleep_rem", "sleep_awake")
_DEVICE_VITAL_FIELDS = (
    "blood_pressure_systolic", "blood_pressure_diastolic", "heart_rate",
    "blood_oxygen", "resting_heart_rate", "body_temperature", "weight",
    "respiratory_rate",
)
_VECTORIZED_VITALS = {
    "heart_rate", "resting_heart_rate", "systolic_bp", "diastolic_bp",
    "spo2", "temperature", "respiratory_rate", "weight",
}


class FitnessUploadService:
    def __init__(
        self,
        clickhouse_store,
        fitness_sync_store,
        postgres_store: PostgresStore,
    ):
        self.clickhouse_store = clickhouse_store
        self.fitness_sync_store = fitness_sync_store
        self.postgres_store = postgres_store

    @with_postgres_session
    async def process_fitness_data(
        self,
        patient_id: str,
        fitness_data: FitnessDataRequest,
        *,
        postgres_session: AsyncSession,
    ) -> datetime:
        start_datetime, end_datetime = (
            fitness_data.start_datetime,
            fitness_data.end_datetime,
        )

        await self.insert_new_data(
            patient_id, fitness_data, postgres_session=postgres_session
        )
        await self.update_last_sync(patient_id, end_datetime)

        # Commit the session to save all changes
        await postgres_session.commit()

        span = dates_between(start_datetime.date(), end_datetime.date())
        await mark_dirty(patient_id, DataDomain.FITNESS, span)
        if any(getattr(fitness_data, f, None) for f in _SLEEP_FIELDS):
            await mark_dirty(patient_id, DataDomain.SLEEP, span)
        if any(getattr(fitness_data, f, None) for f in _DEVICE_VITAL_FIELDS):
            await mark_dirty(patient_id, DataDomain.VITALS, span)
        if fitness_data.blood_glucose:
            await mark_dirty(patient_id, DataDomain.SMBG, span)

        # Gamification hook (fire-and-forget)
        try:
            from uuid import UUID as _UUID
            from lib.core.container import container
            from lib.services.gamification.event_handler import GamificationEventHandler
            handler = container.resolve(GamificationEventHandler)

            # Sum only today's steps (filter by end_datetime date to exclude multi-day batches)
            steps = None
            if fitness_data.steps:
                today_date = end_datetime.date()
                today_steps = [
                    item for item in fitness_data.steps
                    if parse(item.start_datetime).date() == today_date
                ]
                steps = sum(item.value for item in today_steps) or None

            # Detect workouts
            workout_completed = bool(fitness_data.workouts)

            await handler.on_fitness_synced(
                _UUID(patient_id), steps=steps, workout_completed=workout_completed
            )

            # Glucose via HealthKit
            if fitness_data.blood_glucose:
                await handler.on_glucose_synced(_UUID(patient_id))

            # Weight via HealthKit
            if fitness_data.weight:
                await handler.on_weight_logged(_UUID(patient_id))
                try:
                    from lib.utils.sync_profile_weight import sync_profile_weight
                    latest = max(fitness_data.weight, key=lambda w: w.end_datetime)
                    await sync_profile_weight(patient_id, float(latest.value))
                except Exception:
                    pass

            # Sleep via HealthKit / wearable — completes the "Log your sleep" task
            # for patients who never open the app's daily check-in.
            if (fitness_data.sleep_deep or fitness_data.sleep_light
                    or fitness_data.sleep_rem or fitness_data.sleep_in_bed
                    or fitness_data.sleep_awake):
                await handler.on_sleep_logged(_UUID(patient_id))
        except Exception:
            pass

        return end_datetime

    @with_postgres_session
    async def insert_new_data(
        self,
        patient_id: str,
        fitness_data: FitnessDataRequest,
        *,
        postgres_session: AsyncSession,
    ):
        # Insert fitness data into ClickHouse
        fitness_items = (
            fitness_data.steps
            + fitness_data.active_energy_burned
            + fitness_data.distance_walking_running
            + fitness_data.flights_climbed
            + fitness_data.exercise_time
            + fitness_data.workouts
        )
        data_points = [
            {
                "patient_id": patient_id,
                "type": item.type,
                "source_name": item.source_name,
                "source_platform": item.source_platform,
                "unit": item.unit,
                "value": float(item.value),
                "start_datetime": parse(item.start_datetime).replace(tzinfo=None),
                "end_datetime": parse(item.end_datetime).replace(tzinfo=None),
            }
            for item in fitness_items
        ]
        await self.clickhouse_store.awrite_data("aihealth.fitness_data", data_points)

        # Insert sleep data into ClickHouse
        sleep_data_points = [
            {
                "patient_id": patient_id,
                "type": sleep_type,
                "source_name": item.source_name,
                "source_platform": item.source_platform,
                "sleep_duration": float(item.value),
                "sleep_start_time": parse(item.start_datetime).replace(tzinfo=None),
                "sleep_end_time": parse(item.end_datetime).replace(tzinfo=None),
            }
            for sleep_type, sleep_data in [
                ("sleep_in_bed", fitness_data.sleep_in_bed),
                ("sleep_deep", fitness_data.sleep_deep),
                ("sleep_light", fitness_data.sleep_light),
                ("sleep_rem", fitness_data.sleep_rem),
                ("sleep_awake", fitness_data.sleep_awake),
            ]
            for item in sleep_data
        ]
        await self.clickhouse_store.awrite_data("aihealth.sleep_data", sleep_data_points)

        # Insert vitals into ClickHouse (HR, BP)
        vitals_data_points: list[dict] = []
        for diastolic_item, systolic_item in zip(
            fitness_data.blood_pressure_diastolic,
            fitness_data.blood_pressure_systolic,
        ):
            t = parse(diastolic_item.start_datetime).replace(tzinfo=None)
            vitals_data_points.append({
                "patient_id": patient_id, "type": "diastolic_bp",
                "value": diastolic_item.value, "time": t,
                "source_name": diastolic_item.source_name,
                "source_platform": diastolic_item.source_platform,
            })
            vitals_data_points.append({
                "patient_id": patient_id, "type": "systolic_bp",
                "value": systolic_item.value, "time": t,
                "source_name": systolic_item.source_name,
                "source_platform": systolic_item.source_platform,
            })

        for item in fitness_data.heart_rate:
            vitals_data_points.append({
                "patient_id": patient_id, "type": "heart_rate",
                "value": item.value,
                "time": parse(item.start_datetime).replace(tzinfo=None),
                "source_name": item.source_name,
                "source_platform": item.source_platform,
            })

        for vital_type, vital_data in [
            ("blood_oxygen", fitness_data.blood_oxygen),
            ("resting_heart_rate", fitness_data.resting_heart_rate),
            ("body_temperature", fitness_data.body_temperature),
            ("weight", fitness_data.weight),
            ("respiratory_rate", fitness_data.respiratory_rate),
        ]:
            for item in vital_data:
                vitals_data_points.append({
                    "patient_id": patient_id, "type": canonical_vital_type(vital_type),
                    "value": item.value,
                    "time": parse(item.start_datetime).replace(tzinfo=None),
                    "source_name": item.source_name,
                    "source_platform": item.source_platform,
                })

        if vitals_data_points:
            await self.clickhouse_store.awrite_data("aihealth.vitals_data", vitals_data_points)
            await self._enqueue_vitals_vector(patient_id, vitals_data_points)

        if fitness_data.blood_glucose:
            values = [
                {
                    "patient_id": patient_id,
                    "glucose_level": item.value,
                    "reading_time": parse(item.start_datetime).replace(tzinfo=None),
                    "source_name": item.source_name,
                    "source_platform": item.source_platform,
                    # Device readings carry no meal context; "random" is the
                    # canonical bucket the SMBG report groups them under.
                    "type": "random",
                }
                for item in fitness_data.blood_glucose
            ]
            stmt = pg_insert(PatientSMBG).values(values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_smbg_patient_time_source",
                set_={
                    "glucose_level": stmt.excluded.glucose_level,
                    "source_platform": stmt.excluded.source_platform,
                    "type": stmt.excluded.type,
                },
            ).returning(
                PatientSMBG.id,
                PatientSMBG.glucose_level,
                PatientSMBG.reading_time,
                PatientSMBG.type,
                PatientSMBG.source_name,
                PatientSMBG.uploaded_at,
            )
            upserted = (await postgres_session.execute(stmt)).all()
            await self._enqueue_smbg_vectors(patient_id, upserted)

    async def _enqueue_smbg_vectors(self, patient_id: str, rows: list) -> None:
        """Vectorize device-synced glucose so it reaches RAG and the proactive
        monitor, like manually-entered SMBG. Bounded to the recent window —
        a first-connect HealthKit backfill must not fan out one vector job
        (and one proactive event) per historical reading."""
        from datetime import datetime, timedelta

        from lib.workers.tasks.smbg.enqueue import enqueue_generate_smbg_vector_async

        cutoff = datetime.utcnow() - timedelta(days=7)
        recent = [r for r in rows if r.reading_time >= cutoff][:100]
        for r in recent:
            try:
                await enqueue_generate_smbg_vector_async(
                    patient_id=patient_id,
                    reading_id=str(r.id),
                    reading_data={
                        "glucose_mgdl": r.glucose_level,
                        "reading_time": r.reading_time.isoformat(),
                        "type": r.type,
                        "notes": None,
                        "uploaded_at": r.uploaded_at,
                        "source": r.source_name or "device",
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to enqueue device SMBG vector for {patient_id}: {e}")

    async def _enqueue_vitals_vector(self, patient_id: str, points: list[dict]) -> None:
        latest: dict[str, dict] = {}
        for p in points:
            key = canonical_vital_type(p["type"])
            if key in _VECTORIZED_VITALS and (key not in latest or p["time"] > latest[key]["time"]):
                latest[key] = p
        if not latest:
            return
        newest = max(latest.values(), key=lambda p: p["time"])
        snapshot: dict = {key: p["value"] for key, p in latest.items()}
        snapshot.update({
            "test_time": newest["time"],
            "source_name": newest.get("source_name") or "wearable",
            "source_platform": newest.get("source_platform") or "",
        })
        vital_id = f"fitness:{patient_id}:{newest['time'].date()}"
        await enqueue_generate_vital_vector_async(patient_id, vital_id, snapshot)

    async def update_last_sync(self, patient_id: str, dateTo: datetime):
        fitness_sync_key = f"fitness_sync:{patient_id}"

        # Set or update the sync timestamp in Redis
        self.fitness_sync_store.set_key(
            fitness_sync_key,
            value=dateTo.isoformat(),
        )
