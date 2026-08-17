#!/usr/bin/env python
"""
Demo Environment Seeder & Data Replay Tool.

Creates a demo health facility, care provider, and anonymous patient,
then replays a real patient's data through API calls so every downstream
pipeline (vectors, insights, gamification, proactive monitor, health agent)
fires naturally.

Usage:
  # 1. Create demo infrastructure
  python scripts/demo/seed_demo.py setup

  # 2. Find a data-rich patient to clone from
  python scripts/demo/seed_demo.py list-rich-patients

  # 3. Replay their data into the demo patient
  python scripts/demo/seed_demo.py replay \
    --source-patient-id <uuid> \
    --start-date 2026-01-01 \
    --end-date 2026-06-15 \
    --server-url http://localhost:8000

  # Replay only specific data types
  python scripts/demo/seed_demo.py replay \
    --source-patient-id <uuid> \
    --start-date 2026-01-01 \
    --end-date 2026-06-15 \
    --data-types profile meals prescriptions memories

Data types replayed:
  profile          Patient lifestyle, medical history, allergies, etc.
  meals            Meals with food items + nutrition (triggers vectors, insights)
  workouts         Gym sessions with exercises and sets
  smbg             Self-monitored blood glucose readings
  sleep            Sleep check-ins
  mood             Mood entries
  symptoms         Symptom logs
  prescriptions    Prescriptions + medications (via care provider)
  diet_plans       Active diet plans (via care provider)
  fitness_plans    Active fitness plans (via care provider)
  cgm              CGM data from ClickHouse (uploaded as LibreView CSV)
  fitness          Fitness & vitals from ClickHouse (steps, HR, BP, etc.)
  memories         AI memory facts from MongoDB (health agent context)

Requires: httpx, asyncpg, sqlalchemy, clickhouse-driver, python-decouple,
          motor (for MongoDB), jose (for JWT), passlib (for password hashing)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

import httpx
from decouple import config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

POSTGRES_URL = config("POSTGRES_ASYNCPG_URL")
CLICKHOUSE_HOST = config("CLICKHOUSE_HOST", default="localhost")
CLICKHOUSE_PORT = config("CLICKHOUSE_PORT", default="9000", cast=int)
CLICKHOUSE_USER = config("CLICKHOUSE_USER", default="default")
CLICKHOUSE_PASSWORD = config("CLICKHOUSE_PASSWORD", default="")

JWT_SECRET = config("JWT_SECRET")
JWT_ALGORITHM = config("JWT_ALGORITHM")
JWT_AUDIENCE = config("JWT_AUDIENCE")

DEMO_FACILITY_NAME = "AiHealth Demo Clinic"
DEMO_FACILITY_SUBDOMAIN = "demo-clinic"
DEMO_FACILITY_EMAIL = "demo-clinic@ahealth.in"

DEMO_PROVIDER_EMAIL = "demo-provider@ahealth.in"
DEMO_PROVIDER_PASSWORD = "demo1234"
DEMO_PROVIDER_FIRST = "Demo"
DEMO_PROVIDER_LAST = "Provider"

DEMO_PATIENT_PREFIX = "Demo Patient"

STATE_FILE = Path(__file__).parent / ".demo_state.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_jwt(user_id: str, role: str) -> str:
    from jose import jwt as jose_jwt

    return jose_jwt.encode(
        {"sub": user_id, "role": role, "aud": JWT_AUDIENCE},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def ch_client():
    from clickhouse_driver import Client

    return Client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD.strip(),
        send_receive_timeout=300,
    )


def pg_engine():
    return create_async_engine(POSTGRES_URL)


# ---------------------------------------------------------------------------
# SETUP command
# ---------------------------------------------------------------------------


async def cmd_setup(args):
    engine = pg_engine()
    state = load_state()

    async with engine.begin() as conn:
        # -- Health facility ---------------------------------------------------
        existing = await conn.execute(
            text("SELECT health_facility_id FROM health_facilities WHERE subdomain = :sub"),
            {"sub": DEMO_FACILITY_SUBDOMAIN},
        )
        row = existing.first()
        if row:
            facility_id = str(row[0])
            print(f"  Facility already exists: {facility_id}")
        else:
            facility_id = str(uuid.uuid4())
            await conn.execute(
                text("""
                    INSERT INTO health_facilities
                        (health_facility_id, name, phone_number, email, address,
                         facility_type, subdomain, custom_domain, created_at, updated_at)
                    VALUES
                        (:id, :name, :phone, :email, :addr, :ftype, :sub, :domain,
                         NOW(), NOW())
                """),
                {
                    "id": facility_id,
                    "name": DEMO_FACILITY_NAME,
                    "phone": "+910000000000",
                    "email": DEMO_FACILITY_EMAIL,
                    "addr": "Demo Address",
                    "ftype": "clinic",
                    "sub": DEMO_FACILITY_SUBDOMAIN,
                    "domain": "demo-clinic.ahealth.in",
                },
            )
            print(f"  Created facility: {facility_id}")

        state["facility_id"] = facility_id

        # -- Care provider -----------------------------------------------------
        existing = await conn.execute(
            text("SELECT care_provider_id FROM care_providers WHERE email = :email"),
            {"email": DEMO_PROVIDER_EMAIL},
        )
        row = existing.first()
        if row:
            provider_id = str(row[0])
            print(f"  Care provider already exists: {provider_id}")
        else:
            from passlib.context import CryptContext

            pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
            provider_id = str(uuid.uuid4())
            code = str(uuid.uuid4().int)[:6]
            await conn.execute(
                text("""
                    INSERT INTO care_providers
                        (care_provider_id, code, first_name, last_name, phone_number,
                         email, role, hashed_password, medical_council_number,
                         status, is_verified, health_facility_id, created_at, updated_at,
                         permissions)
                    VALUES
                        (:id, :code, :first, :last, :phone, :email, :role,
                         :pwd, :mcn, 'ACTIVE', true, :fid, NOW(), NOW(),
                         CAST(:perms AS jsonb))
                """),
                {
                    "id": provider_id,
                    "code": code,
                    "first": DEMO_PROVIDER_FIRST,
                    "last": DEMO_PROVIDER_LAST,
                    "phone": "+910000000001",
                    "email": DEMO_PROVIDER_EMAIL,
                    "role": "Doctor",
                    "pwd": pwd_ctx.hash(DEMO_PROVIDER_PASSWORD),
                    "mcn": f"DEMO-{code}",
                    "fid": facility_id,
                    # Shape must match has_care_provider_permission:
                    # {feature: {action: bool}} with "read", not "view".
                    "perms": json.dumps({
                        feature: {
                            "read": True,
                            "create": True,
                            "update": True,
                            "delete": True,
                        }
                        for feature in [
                            "patients",
                            "reports",
                            "meals",
                            "prescriptions",
                            "fitness_plans",
                            "diet_plans",
                            "cgms",
                            "fitness",
                        ]
                    }),
                },
            )
            print(f"  Created care provider: {provider_id}")

        state["provider_id"] = provider_id
        state["provider_email"] = DEMO_PROVIDER_EMAIL
        state["provider_password"] = DEMO_PROVIDER_PASSWORD
        state["provider_token"] = create_jwt(provider_id, "CARE_PROVIDER")

        # -- Demo patient (anonymous) ------------------------------------------
        patient_label = f"{DEMO_PATIENT_PREFIX} A"
        existing = await conn.execute(
            text("SELECT patient_id FROM patients WHERE email = :email"),
            {"email": "demo-patient-a@ahealth.in"},
        )
        row = existing.first()
        if row:
            patient_id = str(row[0])
            print(f"  Demo patient already exists: {patient_id}")
        else:
            patient_id = str(uuid.uuid4())
            await conn.execute(
                text("""
                    INSERT INTO patients
                        (patient_id, first_name, last_name, email, phone_number,
                         dob, gender, height_cm, weight_kg, timezone,
                         is_verified, health_facility_id, created_at, updated_at,
                         profile_completion)
                    VALUES
                        (:id, :first, :last, :email, :phone,
                         :dob, :gender, :height, :weight, :tz,
                         true, :fid, NOW(), NOW(), CAST(:pc AS jsonb))
                """),
                {
                    "id": patient_id,
                    "first": "Demo",
                    "last": "Patient A",
                    "email": "demo-patient-a@ahealth.in",
                    "phone": "+910000000002",
                    "dob": date(1990, 6, 15),
                    "gender": "MALE",
                    "height": 175.0,
                    "weight": 78.0,
                    "tz": "Asia/Kolkata",
                    "fid": facility_id,
                    "pc": json.dumps({
                        "basic": {"is_complete": True, "is_mandatory": True},
                        "lifestyle": {"is_complete": True, "is_mandatory": True},
                        "medical_history": {"is_complete": True, "is_mandatory": True},
                    }),
                },
            )
            print(f"  Created demo patient: {patient_id}")

        # Link patient → care provider
        existing = await conn.execute(
            text("""
                SELECT 1 FROM patient_care_provider_association
                WHERE patient_id = :pid AND care_provider_id = :cpid
            """),
            {"pid": patient_id, "cpid": provider_id},
        )
        if not existing.first():
            await conn.execute(
                text("""
                    INSERT INTO patient_care_provider_association (patient_id, care_provider_id)
                    VALUES (:pid, :cpid)
                """),
                {"pid": patient_id, "cpid": provider_id},
            )
            print("  Linked patient ↔ care provider")

        state["patient_id"] = patient_id
        state["patient_token"] = create_jwt(patient_id, "PATIENT")

    await engine.dispose()
    save_state(state)

    print("\n✓ Demo environment ready!\n")
    print(f"  Facility ID:        {state['facility_id']}")
    print(f"  Care Provider ID:   {state['provider_id']}")
    print(f"  Provider Login:     {DEMO_PROVIDER_EMAIL} / {DEMO_PROVIDER_PASSWORD}")
    print(f"  Demo Patient ID:    {state['patient_id']}")
    print(f"  Patient JWT:        {state['patient_token'][:40]}...")
    print(f"  Provider JWT:       {state['provider_token'][:40]}...")
    print(f"\n  State saved to {STATE_FILE}")


# ---------------------------------------------------------------------------
# REPLAY command
# ---------------------------------------------------------------------------

BATCH_DELAY = 0.3  # seconds between API calls to avoid overloading

MONGO_URI = config("MONGO_URI", default="")
MONGO_DB = config("MONGO_DB", default="aihealth")


def mongo_client():
    from motor.motor_asyncio import AsyncIOMotorClient

    return AsyncIOMotorClient(MONGO_URI)


async def cmd_replay(args):
    state = load_state()
    if not state.get("patient_id"):
        print("ERROR: Run 'setup' first.")
        sys.exit(1)

    demo_pid = state["patient_id"]
    patient_token = state["patient_token"]
    provider_token = state["provider_token"]
    source_pid = args.source_patient_id
    start = datetime.strptime(args.start_date, "%Y-%m-%d")
    end = datetime.strptime(args.end_date, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59
    )
    base_url = args.server_url.rstrip("/")

    print(f"\nReplaying data from patient {source_pid}")
    print(f"  → into demo patient {demo_pid}")
    print(f"  Date range: {args.start_date} to {args.end_date}")
    print(f"  Server: {base_url}\n")

    engine = pg_engine()

    patient_headers = {"Authorization": f"Bearer {patient_token}"}
    provider_headers = {"Authorization": f"Bearer {provider_token}"}

    async with httpx.AsyncClient(
        base_url=base_url, headers=patient_headers, timeout=60.0
    ) as patient_client, httpx.AsyncClient(
        base_url=base_url, headers=provider_headers, timeout=60.0
    ) as provider_client:
        async with engine.connect() as conn:
            if "profile" in args.data_types:
                await replay_profile(conn, patient_client, source_pid, demo_pid)
            if "meals" in args.data_types:
                await replay_meals(conn, patient_client, source_pid, demo_pid, start, end)
            if "workouts" in args.data_types:
                await replay_workouts(conn, patient_client, source_pid, demo_pid, start, end)
            if "smbg" in args.data_types:
                await replay_smbg(conn, patient_client, source_pid, demo_pid, start, end)
            if "sleep" in args.data_types:
                await replay_sleep(conn, patient_client, source_pid, demo_pid, start, end)
            if "mood" in args.data_types:
                await replay_mood(conn, patient_client, source_pid, demo_pid, start, end)
            if "symptoms" in args.data_types:
                await replay_symptoms(conn, patient_client, source_pid, demo_pid, start, end)
            if "prescriptions" in args.data_types:
                await replay_prescriptions(conn, provider_client, source_pid, demo_pid, start, end)
            if "diet_plans" in args.data_types:
                await replay_diet_plans(conn, provider_client, source_pid, demo_pid)
            if "fitness_plans" in args.data_types:
                await replay_fitness_plans(conn, provider_client, source_pid, demo_pid)

        if "cgm" in args.data_types:
            await replay_cgm(patient_client, source_pid, demo_pid, start, end)
        if "fitness" in args.data_types:
            await replay_fitness(patient_client, source_pid, demo_pid, start, end)
        if "memories" in args.data_types:
            await replay_memories(patient_client, source_pid, demo_pid)

    await engine.dispose()
    print("\n✓ Replay complete!")


# -- Profile ---------------------------------------------------------------

async def replay_profile(
    conn: AsyncSession,
    client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
):
    print("── Profile (lifestyle + medical history) ──")

    # Read source patient basics
    p = (await conn.execute(
        text("SELECT gender, height_cm, weight_kg, waist_cm, hip_cm, timezone, occupation FROM patients WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).first()
    if not p:
        print("  Source patient not found, skipping profile")
        return

    # Daily activity
    da = (await conn.execute(
        text("SELECT activity_level FROM patient_daily_activity WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).first()

    # Eating habit
    eh = (await conn.execute(
        text("SELECT meals_per_day, snacks_count, diet_preferences_detail FROM patient_eating_habits WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).first()
    diet_prefs = (await conn.execute(
        text("SELECT preference FROM patient_diet_preferences WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).fetchall()
    meal_timings = (await conn.execute(
        text("SELECT meal_type, time FROM patient_meal_timings WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).fetchall()

    # Alcohol
    alc = (await conn.execute(
        text("SELECT status, frequency, drinks_per_session, type_of_alcohol, quit_years_ago FROM patient_alcohol_consumption WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).first()

    # Smoking
    smk = (await conn.execute(
        text("SELECT status, smoke_type, cigarettes_per_day, years_of_smoking, quit_years_ago FROM patient_smoking_habit WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).first()

    # Sleep habit
    slp = (await conn.execute(
        text("SELECT sleep_quality, average_sleep_hours, bed_time, wake_up_time, wake_up_fresh, drowsy_day, snores FROM patient_sleep_habit WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).first()

    # Food allergies
    fa = (await conn.execute(
        text("SELECT name, name_other, severity FROM patient_food_allergies WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).fetchall()

    # Drug allergies
    dra = (await conn.execute(
        text("SELECT name, name_other, reaction FROM patient_drug_allergies WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).fetchall()

    # Diabetic history
    dh = (await conn.execute(
        text("SELECT type_of_diabetes, years_with_diabetes, diagnosed_at FROM patient_diabetic_history WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).first()

    # Family diabetic history
    fdh = (await conn.execute(
        text("SELECT family_member, type_of_diabetes, years_with_diabetes FROM patient_family_diabetic_histories WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).fetchall()

    # Medical history
    mh = (await conn.execute(
        text("SELECT condition, condition_other, status, duration_years, started_at, details FROM patient_medical_histories WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).fetchall()

    # Reproductive health
    rh = (await conn.execute(
        text("SELECT is_pregnant, pregnancy_weeks, menopause_status, period_regularity, uses_contraception FROM patient_reproductive_health WHERE patient_id = :pid"),
        {"pid": source_pid},
    )).first()

    body = {
        "first_name": "Demo",
        "last_name": "Patient A",
        "gender": p[0] or "MALE",
        "dob": "1990-06-15",
        "timezone": p[5] or "Asia/Kolkata",
        "occupation": p[6],
        "height_cm": float(p[1]) if p[1] else 170.0,
        "weight_kg": float(p[2]) if p[2] else 70.0,
        "waist_cm": float(p[3]) if p[3] else None,
        "hip_cm": float(p[4]) if p[4] else None,
        "daily_activity": {"activity_level": da[0] if da else "MODERATE"},
        "eating_habit": {
            "meals_per_day": eh[0] if eh else 3,
            "snacks_count": eh[1] if eh else 1,
            "diet_preferences": [dp[0] for dp in diet_prefs] if diet_prefs else [],
            "diet_preferences_detail": eh[2] if eh else None,
            "cuisine_preferences": [],
            "meal_timings": [
                {"meal_type": mt[0], "time": mt[1].isoformat() if mt[1] else "12:00:00"}
                for mt in meal_timings
            ] if meal_timings else [],
        },
        "alcohol_consumption": {
            "status": alc[0] if alc else "NEVER",
            "frequency": alc[1] if alc else None,
            "drinks_per_session": alc[2] if alc else None,
            "type_of_alcohol": alc[3] if alc and alc[3] else [],
            "quit_years_ago": alc[4] if alc else None,
        },
        "smoking_habit": {
            "status": smk[0] if smk else "NEVER",
            "smoke_type": smk[1] if smk and smk[1] else [],
            "cigarettes_per_day": smk[2] if smk else None,
            "years_of_smoking": float(smk[3]) if smk and smk[3] else None,
            "quit_years_ago": smk[4] if smk else None,
        },
        "sleep_habit": {
            "sleep_quality": slp[0] if slp else "AVERAGE",
            "average_sleep_hours": float(slp[1]) if slp and slp[1] else None,
            "bed_time": slp[2].isoformat() if slp and slp[2] else None,
            "wake_up_time": slp[3].isoformat() if slp and slp[3] else None,
            "wake_up_fresh": slp[4] if slp else None,
            "drowsy_day": slp[5] if slp else None,
            "snores": slp[6] if slp else None,
        },
        "food_allergies": [
            {"name": a[0], "name_other": a[1], "severity": a[2]}
            for a in fa
        ] if fa else [],
        "drug_allergies": [
            {"name": a[0], "name_other": a[1], "reaction": a[2]}
            for a in dra
        ] if dra else [],
        "diabetic_history": {
            "type_of_diabetes": dh[0] if dh else "NONE",
            "years_with_diabetes": float(dh[1]) if dh and dh[1] else None,
            "diagnosed_at": dh[2].isoformat() if dh and dh[2] else None,
        },
        "family_diabetic_histories": [
            {
                "family_member": f[0],
                "type_of_diabetes": f[1],
                "years_with_diabetes": float(f[2]) if f[2] else None,
            }
            for f in fdh
        ] if fdh else [],
        "medical_histories": [
            {
                "condition": m[0],
                "condition_other": m[1],
                "status": m[2],
                "duration_years": float(m[3]) if m[3] else 0,
                "started_at": m[4].isoformat() if m[4] else None,
                "details": m[5],
            }
            for m in mh
        ] if mh else [],
    }

    if rh:
        body["reproductive_health"] = {
            "is_pregnant": rh[0],
            "pregnancy_weeks": rh[1],
            "menopause_status": rh[2],
            "period_regularity": rh[3],
            "uses_contraception": rh[4],
        }

    resp = await client.post("/v1/patients/onboarding", json=body)
    status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
    print(f"  {status} Profile replicated (gender={p[0]}, diabetic_type={dh[0] if dh else 'NONE'}, {len(mh)} conditions, {len(fa)} food allergies)")
    if resp.status_code != 200:
        print(f"       {resp.text[:300]}")


# -- Meals ------------------------------------------------------------------

async def replay_meals(
    conn: AsyncSession,
    client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
    start: datetime,
    end: datetime,
):
    print("── Meals ──")
    rows = await conn.execute(
        text("""
            SELECT m.id, m.name, m.slot, m.date, m.time, m.source, m.image_url,
                   m.image_urls, m.audio_url, m.description, m.note, m.tags
            FROM patient_meals m
            WHERE m.patient_id = :pid
              AND m.date >= :start AND m.date <= :end
            ORDER BY m.date, m.time
        """),
        {"pid": source_pid, "start": start.date(), "end": end.date()},
    )
    meals = rows.fetchall()
    print(f"  Found {len(meals)} meals")

    for meal in meals:
        meal_id = str(meal[0])
        meal_name = meal[1] or "Unnamed meal"
        slot = meal[2] or "snack"
        meal_date = meal[3]
        meal_time = meal[4] or time(12, 0)
        source = meal[5] or "manual"
        image_url = meal[6]
        image_urls = meal[7]
        audio_url = meal[8]
        description = meal[9]
        note = meal[10]
        tags = meal[11] or []

        consumed_at = datetime.combine(meal_date, meal_time)

        items_rows = await conn.execute(
            text("""
                SELECT fi.name, fi.serving_quantity, fi.serving_unit, fi.serving_size,
                       fi.category,
                       mac.calories, mac.proteins, mac.carbohydrates, mac.simple_carbs,
                       mac.complex_carbs, mac.fats, mac.fiber,
                       mic.calcium, mic.iron, mic.zinc, mic.magnesium
                FROM patient_food_items fi
                LEFT JOIN patient_macro_nutritional_values mac ON mac.food_item_id = fi.id
                LEFT JOIN patient_micro_nutritional_values mic ON mic.food_item_id = fi.id
                WHERE fi.meal_id = :mid
            """),
            {"mid": meal_id},
        )
        items = items_rows.fetchall()

        extracted_items = []
        for it in items:
            extracted_items.append({
                "name": it[0] or "Unknown item",
                "portion": float(it[1]) if it[1] else 1.0,
                "unit": it[2] or "serving",
                "macros": {
                    "calories": float(it[5] or 0),
                    "protein": float(it[6] or 0),
                    "carbs": float(it[7] or 0),
                    "carbs_simple": float(it[8] or 0),
                    "carbs_complex": float(it[9] or 0),
                    "fat": float(it[10] or 0),
                    "fiber": float(it[11] or 0),
                },
                "micros": {
                    "calcium_mg": float(it[12] or 0) if it[12] else None,
                    "iron_mg": float(it[13] or 0) if it[13] else None,
                    "zinc_mg": float(it[14] or 0) if it[14] else None,
                    "magnesium_mg": float(it[15] or 0) if it[15] else None,
                },
                "tags": [],
            })

        totals_row = await conn.execute(
            text("""
                SELECT mac.calories, mac.proteins, mac.carbohydrates, mac.simple_carbs,
                       mac.complex_carbs, mac.fats, mac.fiber,
                       mic.calcium, mic.iron, mic.zinc, mic.magnesium
                FROM patient_total_macro_nutritional_values mac
                LEFT JOIN patient_total_micro_nutritional_values mic
                    ON mic.meal_id = mac.meal_id
                WHERE mac.meal_id = :mid
            """),
            {"mid": meal_id},
        )
        totals = totals_row.first()

        total_macros = {}
        total_micros = {}
        if totals:
            total_macros = {
                "calories": float(totals[0] or 0),
                "protein": float(totals[1] or 0),
                "carbs": float(totals[2] or 0),
                "carbs_simple": float(totals[3] or 0),
                "carbs_complex": float(totals[4] or 0),
                "fat": float(totals[5] or 0),
                "fiber": float(totals[6] or 0),
            }
            total_micros = {
                "calcium_mg": float(totals[7] or 0) if totals[7] else None,
                "iron_mg": float(totals[8] or 0) if totals[8] else None,
                "zinc_mg": float(totals[9] or 0) if totals[9] else None,
                "magnesium_mg": float(totals[10] or 0) if totals[10] else None,
            }

        valid_sources = {"photo", "text", "voice", "repeat", "manual"}
        meal_source = source if source in valid_sources else "manual"

        body = {
            "slot": slot,
            "source": meal_source,
            "consumed_at": consumed_at.isoformat(),
            "extraction": {
                "name": meal_name,
                "items": extracted_items,
                "total_macros": total_macros,
                "total_micros": total_micros,
                "tags": tags,
                "overall_confidence": "high",
            },
            "image_url": image_url,
            "image_urls": image_urls,
            "audio_url": audio_url,
            "description": description,
            "note": note,
        }

        resp = await client.post(f"/v1/meals/{demo_pid}", json=body)
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        print(f"  {status} {consumed_at.date()} {slot}: {meal_name}")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(BATCH_DELAY)


# -- Workouts ---------------------------------------------------------------

async def replay_workouts(
    conn: AsyncSession,
    client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
    start: datetime,
    end: datetime,
):
    print("── Workouts ──")
    rows = await conn.execute(
        text("""
            SELECT w.id, w.date, w.time, w.type, w.duration_minutes,
                   w.intensity, w.calories_burned, w.notes, w.image_url, w.source
            FROM patient_workouts w
            WHERE w.patient_id = :pid
              AND w.date >= :start AND w.date <= :end
            ORDER BY w.date, w.time
        """),
        {"pid": source_pid, "start": start.date(), "end": end.date()},
    )
    workouts = rows.fetchall()
    print(f"  Found {len(workouts)} workouts")

    for w in workouts:
        workout_id = str(w[0])

        ex_rows = await conn.execute(
            text("""
                SELECT e.exercise_id, e.exercise_name, e.order_index,
                       e.sets, e.reps, e.weight_kg, e.duration_seconds, e.distance_m,
                       e.notes, e.id
                FROM patient_workout_exercises e
                WHERE e.workout_id = :wid
                ORDER BY e.order_index
            """),
            {"wid": workout_id},
        )
        exercises = ex_rows.fetchall()

        exercise_items = []
        for ex in exercises:
            ex_entry = {
                "exercise_id": ex[0],
                "order_index": ex[2],
                "sets": ex[3],
                "reps": ex[4],
                "weight_kg": float(ex[5]) if ex[5] else None,
                "duration_seconds": ex[6],
                "distance_m": float(ex[7]) if ex[7] else None,
                "notes": ex[8],
            }

            set_rows = await conn.execute(
                text("""
                    SELECT set_number, reps, weight_kg, duration_seconds, distance_m
                    FROM patient_workout_sets
                    WHERE workout_exercise_id = :eid
                    ORDER BY set_number
                """),
                {"eid": str(ex[9])},
            )
            sets = set_rows.fetchall()
            if sets:
                ex_entry["set_details"] = [
                    {
                        "set_number": s[0],
                        "reps": s[1],
                        "weight_kg": float(s[2]) if s[2] else None,
                        "duration_seconds": s[3],
                        "distance_m": float(s[4]) if s[4] else None,
                    }
                    for s in sets
                ]

            exercise_items.append(ex_entry)

        body = {
            "date": w[1].isoformat(),
            "time": w[2].isoformat() if w[2] else None,
            "type": w[3],
            "duration_minutes": w[4],
            "intensity": w[5],
            "calories_burned": float(w[6]) if w[6] else None,
            "notes": w[7],
            "image_url": w[8],
            "source": w[9] or "app",
            "exercises": exercise_items,
        }

        resp = await client.post(f"/v1/patients/{demo_pid}/workouts", json=body)
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        print(f"  {status} {w[1]} {w[3]}: {len(exercise_items)} exercises")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(BATCH_DELAY)


# -- SMBG -------------------------------------------------------------------

async def replay_smbg(
    conn: AsyncSession,
    client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
    start: datetime,
    end: datetime,
):
    print("── SMBG readings ──")
    rows = await conn.execute(
        text("""
            SELECT glucose_level, reading_time, source_name, source_platform,
                   type, notes
            FROM patient_smbgs
            WHERE patient_id = :pid
              AND reading_time >= :start AND reading_time <= :end
            ORDER BY reading_time
        """),
        {"pid": source_pid, "start": start, "end": end},
    )
    readings = rows.fetchall()
    print(f"  Found {len(readings)} SMBG readings")

    for r in readings:
        body = {
            "glucose_level": float(r[0]),
            "reading_time": r[1].isoformat(),
            "source_name": r[2],
            "source_platform": r[3],
            "type": r[4],
            "notes": r[5],
        }

        resp = await client.post("/patient/smbgs/upload", json=body)
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        print(f"  {status} {r[1]} glucose={r[0]} mg/dL ({r[4]})")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(BATCH_DELAY)


# -- Sleep ------------------------------------------------------------------

async def replay_sleep(
    conn: AsyncSession,
    client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
    start: datetime,
    end: datetime,
):
    print("── Sleep check-ins ──")
    rows = await conn.execute(
        text("""
            SELECT checkin_date, quality, hours_slept, bed_time, wake_time, notes
            FROM sleep_checkins
            WHERE patient_id = :pid
              AND checkin_date >= :start AND checkin_date <= :end
            ORDER BY checkin_date
        """),
        {"pid": source_pid, "start": start.date(), "end": end.date()},
    )
    checkins = rows.fetchall()
    print(f"  Found {len(checkins)} sleep check-ins")

    for c in checkins:
        body = {
            "checkin_date": c[0].isoformat(),
            "quality": c[1],
            "hours_slept": float(c[2]),
            "bed_time": c[3],
            "wake_time": c[4],
            "notes": c[5],
        }

        resp = await client.post(
            f"/v1/patients/{demo_pid}/checkins/sleep", json=body
        )
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        print(f"  {status} {c[0]} quality={c[1]} hours={c[2]}")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(BATCH_DELAY)


# -- Mood -------------------------------------------------------------------

async def replay_mood(
    conn: AsyncSession,
    client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
    start: datetime,
    end: datetime,
):
    print("── Mood entries ──")
    rows = await conn.execute(
        text("""
            SELECT level, emoji, tags, notes, recorded_at
            FROM mood_entries
            WHERE patient_id = :pid
              AND recorded_at >= :start AND recorded_at <= :end
            ORDER BY recorded_at
        """),
        {"pid": source_pid, "start": start, "end": end},
    )
    entries = rows.fetchall()
    print(f"  Found {len(entries)} mood entries")

    for e in entries:
        body = {
            "level": e[0],
            "emoji": e[1],
            "tags": e[2] or [],
            "notes": e[3],
            "recorded_at": e[4].isoformat(),
        }

        resp = await client.post(
            f"/v1/patients/{demo_pid}/checkins/mood", json=body
        )
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        print(f"  {status} {e[4].date()} level={e[0]} ({e[1]})")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(BATCH_DELAY)


# -- Symptoms ---------------------------------------------------------------

async def replay_symptoms(
    conn: AsyncSession,
    client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
    start: datetime,
    end: datetime,
):
    print("── Symptom entries ──")
    rows = await conn.execute(
        text("""
            SELECT se.id, se.recorded_at, se.notes
            FROM symptom_entries se
            WHERE se.patient_id = :pid
              AND se.recorded_at >= :start AND se.recorded_at <= :end
            ORDER BY se.recorded_at
        """),
        {"pid": source_pid, "start": start, "end": end},
    )
    entries = rows.fetchall()
    print(f"  Found {len(entries)} symptom entries")

    for e in entries:
        entry_id = str(e[0])

        items_rows = await conn.execute(
            text("""
                SELECT symptom_name, severity, custom_label
                FROM symptom_entry_items
                WHERE symptom_entry_id = :eid
            """),
            {"eid": entry_id},
        )
        items = items_rows.fetchall()

        body = {
            "recorded_at": e[1].isoformat(),
            "notes": e[2],
            "symptoms": [
                {
                    "symptom_name": it[0],
                    "severity": it[1],
                    "custom_label": it[2],
                }
                for it in items
            ],
        }

        resp = await client.post(
            f"/v1/patients/{demo_pid}/checkins/symptoms", json=body
        )
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        names = ", ".join(it[0] for it in items)
        print(f"  {status} {e[1].date()} [{names}]")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(BATCH_DELAY)


# -- Prescriptions + Medications --------------------------------------------

async def replay_prescriptions(
    conn: AsyncSession,
    provider_client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
    start: datetime,
    end: datetime,
):
    print("── Prescriptions & Medications ──")
    rows = await conn.execute(
        text("""
            SELECT p.prescription_id, p.doctor_name, p.prescription_date,
                   p.file_urls, p.follow_up_required, p.follow_up_date, p.notes
            FROM patient_prescriptions p
            WHERE p.patient_id = :pid AND p.status = 'confirmed'
              AND p.created_at >= :start AND p.created_at <= :end
            ORDER BY p.created_at
        """),
        {"pid": source_pid, "start": start, "end": end},
    )
    prescriptions = rows.fetchall()
    print(f"  Found {len(prescriptions)} prescriptions")

    for rx in prescriptions:
        rx_id = str(rx[0])

        med_rows = await conn.execute(
            text("""
                SELECT name, brand_name, strength, formulation, route,
                       food_timing, purpose, instructions, doses, schedule,
                       start_date, end_date
                FROM patient_medications
                WHERE prescription_id = :rxid
            """),
            {"rxid": rx_id},
        )
        meds = med_rows.fetchall()

        if not meds:
            continue

        medicines = []
        for m in meds:
            med_entry = {
                "name": m[0],
                "brand_name": m[1],
                "strength": m[2],
                "formulation": m[3],
                "route": m[4],
                "food_timing": m[5],
                "purpose": m[6],
                "instructions": m[7],
                "doses": m[8] if m[8] else [],
                "schedule": m[9] if m[9] else None,
                "start_date": m[10].isoformat() if m[10] else date.today().isoformat(),
                "end_date": m[11].isoformat() if m[11] else None,
                "is_sos": False,
            }
            medicines.append(med_entry)

        body = {
            "doctor_name": rx[1] or "Dr. Demo",
            "prescription_date": rx[2].isoformat() if rx[2] else None,
            "file_urls": rx[3] if rx[3] else [],
            "medicines": medicines,
            "follow_up_required": rx[4] or False,
            "follow_up_date": rx[5].isoformat() if rx[5] else None,
            "notes": rx[6],
        }

        resp = await provider_client.post(
            f"/v1/prescriptions/{demo_pid}/confirm", json=body
        )
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        med_names = ", ".join(m[0] for m in meds)
        print(f"  {status} {rx[2] or '?'}: {len(meds)} meds [{med_names}]")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(BATCH_DELAY)

    # Also replay standalone medications (no prescription)
    standalone = await conn.execute(
        text("""
            SELECT name, brand_name, strength, formulation, route,
                   food_timing, purpose, instructions, doses, schedule,
                   start_date, end_date
            FROM patient_medications
            WHERE patient_id = :pid AND prescription_id IS NULL
              AND status = 'active'
            ORDER BY start_date
        """),
        {"pid": source_pid},
    )
    standalone_meds = standalone.fetchall()

    if standalone_meds:
        print(f"  Found {len(standalone_meds)} standalone medications")
        medicines = []
        for m in standalone_meds:
            medicines.append({
                "name": m[0],
                "brand_name": m[1],
                "strength": m[2],
                "formulation": m[3],
                "route": m[4],
                "food_timing": m[5],
                "purpose": m[6],
                "instructions": m[7],
                "doses": m[8] if m[8] else [],
                "schedule": m[9] if m[9] else None,
                "start_date": m[10].isoformat() if m[10] else date.today().isoformat(),
                "end_date": m[11].isoformat() if m[11] else None,
                "is_sos": False,
            })

        body = {
            "doctor_name": "Dr. Demo",
            "medicines": medicines,
        }
        resp = await provider_client.post(
            f"/v1/prescriptions/{demo_pid}/confirm", json=body
        )
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        print(f"  {status} Standalone: {len(standalone_meds)} medications")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")


# -- Diet Plans -------------------------------------------------------------

async def replay_diet_plans(
    conn: AsyncSession,
    provider_client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
):
    print("── Diet Plans ──")
    rows = await conn.execute(
        text("""
            SELECT calories, protein, carbs, fats, fiber, content,
                   start_date, end_date, status, plan_reason
            FROM patient_diet_plans
            WHERE patient_id = :pid AND status = 'ACTIVE'
            ORDER BY created_at DESC
            LIMIT 3
        """),
        {"pid": source_pid},
    )
    plans = rows.fetchall()
    print(f"  Found {len(plans)} active diet plans")

    for p in plans:
        body = {
            "calories": float(p[0]),
            "protein": float(p[1]),
            "carbs": float(p[2]),
            "fats": float(p[3]),
            "fiber": float(p[4]) if p[4] else None,
            "content": p[5] if p[5] else None,
            "start_date": p[6].isoformat(),
            "end_date": p[7].isoformat() if p[7] else None,
            "status": "ACTIVE",
            "plan_reason": p[9],
        }

        resp = await provider_client.post(
            f"/v1/diet-plans/{demo_pid}", json=body
        )
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        print(f"  {status} {p[0]:.0f} kcal, P{p[1]:.0f}/C{p[2]:.0f}/F{p[3]:.0f}")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(BATCH_DELAY)


# -- Fitness Plans ----------------------------------------------------------

async def replay_fitness_plans(
    conn: AsyncSession,
    provider_client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
):
    print("── Fitness Plans ──")
    rows = await conn.execute(
        text("""
            SELECT steps_goal, content, start_date, end_date, status, plan_reason
            FROM patient_fitness_plans
            WHERE patient_id = :pid AND status = 'ACTIVE'
            ORDER BY created_at DESC
            LIMIT 3
        """),
        {"pid": source_pid},
    )
    plans = rows.fetchall()
    print(f"  Found {len(plans)} active fitness plans")

    for p in plans:
        body = {
            "steps_goal": float(p[0]) if p[0] else None,
            "content": p[1] if p[1] else None,
            "start_date": p[2].isoformat(),
            "end_date": p[3].isoformat() if p[3] else None,
            "status": "ACTIVE",
            "plan_reason": p[5],
        }

        resp = await provider_client.post(
            f"/v1/fitness-plans/{demo_pid}", json=body
        )
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        steps = f"{p[0]:.0f} steps" if p[0] else "custom plan"
        print(f"  {status} {steps}")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(BATCH_DELAY)


# -- AI Memory (MongoDB → API) ---------------------------------------------

async def replay_memories(
    client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
):
    print("── AI Memory ──")

    if not MONGO_URI:
        print("  MONGO_URI not set, skipping memory replay")
        return

    mc = mongo_client()
    db = mc[MONGO_DB]
    collection = db["ai_patient_memory"]

    cursor = collection.find({"patient_id": source_pid})
    facts = await cursor.to_list(length=500)
    mc.close()

    print(f"  Found {len(facts)} memory facts")

    for fact in facts:
        key = fact.get("key", "")
        value = fact.get("value", "")
        if not key or not value:
            continue

        body = {
            "patient_id": demo_pid,
            "key": key,
            "value": str(value)[:2000],
        }

        resp = await client.post("/v1/health-query-agent/memories", json=body)
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        print(f"  {status} {key}: {str(value)[:60]}...")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(0.1)


# -- CGM (ClickHouse → LibreView CSV upload) --------------------------------

async def replay_cgm(
    client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
    start: datetime,
    end: datetime,
):
    print("── CGM data ──")
    ch = ch_client()

    rows = ch.execute(
        """
        SELECT time, glucose_level, record_type, source
        FROM aihealth.cgm_data FINAL
        WHERE patient_id = %(pid)s
          AND time >= %(start)s AND time <= %(end)s
        ORDER BY time
        """,
        {"pid": source_pid, "start": start, "end": end},
    )
    print(f"  Found {len(rows)} CGM readings")

    if not rows:
        return

    # Build a LibreView-format CSV in memory
    import io
    import csv

    buf = io.StringIO()
    # LibreView CSVs have 2 header lines before the data header
    buf.write("FreeStyle LibreLink - Demo Export\n")
    buf.write("\n")

    writer = csv.writer(buf)
    writer.writerow([
        "Device", "Serial Number", "Device Timestamp", "Record Type",
        "Historic Glucose mg/dL", "Scan Glucose mg/dL",
        "Non-numeric Rapid-Acting Insulin", "Rapid-Acting Insulin (units)",
        "Non-numeric Food", "Carbohydrates (grams)", "Carbohydrates (servings)",
        "Non-numeric Long-Acting Insulin", "Long-Acting Insulin Value (units)",
        "Notes", "Strip Glucose mg/dL", "Ketone mmol/L",
    ])

    for row in rows:
        ts = row[0]  # datetime
        glucose = row[1]
        record_type = row[2]
        ts_str = ts.strftime("%d-%m-%Y %I:%M %p")

        historic_glucose = int(glucose) if record_type == "historic" else ""
        scan_glucose = int(glucose) if record_type == "scan" else ""

        writer.writerow([
            "FreeStyle Libre 3", "DEMO-000", ts_str, "0",
            historic_glucose, scan_glucose,
            "", "", "", "", "", "", "", "", "", "",
        ])

    csv_bytes = buf.getvalue().encode("utf-8")

    resp = await client.post(
        "/v1/uploads/libreview",
        params={"patient_id": demo_pid},
        files={"file": ("demo_cgm.csv", csv_bytes, "text/csv")},
    )
    status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
    print(f"  {status} Uploaded {len(rows)} CGM readings as LibreView CSV")
    if resp.status_code != 200:
        print(f"       {resp.text[:300]}")


# -- Fitness / Vitals (ClickHouse → fitness upload) -------------------------

async def replay_fitness(
    client: httpx.AsyncClient,
    source_pid: str,
    demo_pid: str,
    start: datetime,
    end: datetime,
):
    print("── Fitness & Vitals ──")
    ch = ch_client()

    # Fitness data
    fitness_rows = ch.execute(
        """
        SELECT type, source_name, source_platform, unit, value,
               start_datetime, end_datetime
        FROM aihealth.fitness_data FINAL
        WHERE patient_id = %(pid)s
          AND start_datetime >= %(start)s AND start_datetime <= %(end)s
        ORDER BY start_datetime
        """,
        {"pid": source_pid, "start": start, "end": end},
    )
    print(f"  Found {len(fitness_rows)} fitness data points")

    # Vitals data
    vitals_rows = ch.execute(
        """
        SELECT type, value, time, source_name, source_platform
        FROM aihealth.vitals_data FINAL
        WHERE patient_id = %(pid)s
          AND time >= %(start)s AND time <= %(end)s
        ORDER BY time
        """,
        {"pid": source_pid, "start": start, "end": end},
    )
    print(f"  Found {len(vitals_rows)} vitals data points")

    if not fitness_rows and not vitals_rows:
        return

    # Group fitness data by day and batch upload
    from collections import defaultdict

    daily_fitness: dict[date, list] = defaultdict(list)
    for row in fitness_rows:
        day = row[5].date()  # start_datetime
        daily_fitness[day].append(row)

    # Map vitals types to FitnessDataRequest fields
    vitals_type_map = {
        "heart_rate": "heart_rate",
        "blood_oxygen": "blood_oxygen",
        "resting_heart_rate": "resting_heart_rate",
        "body_temperature": "body_temperature",
        "weight": "weight",
        "respiratory_rate": "respiratory_rate",
        "diastolic_bp": "blood_pressure_diastolic",
        "systolic_bp": "blood_pressure_systolic",
    }

    daily_vitals: dict[date, list] = defaultdict(list)
    for row in vitals_rows:
        day = row[2].date()
        daily_vitals[day].append(row)

    all_days = sorted(set(daily_fitness.keys()) | set(daily_vitals.keys()))

    for day in all_days:
        fitness_type_map = {
            "steps": "steps",
            "active_energy_burned": "active_energy_burned",
            "distance_walking_running": "distance_walking_running",
            "flights_climbed": "flights_climbed",
            "exercise_time": "exercise_time",
        }

        body: dict = {
            "start_datetime": datetime.combine(day, time(0, 0)).isoformat(),
            "end_datetime": datetime.combine(day, time(23, 59, 59)).isoformat(),
        }

        # Initialize all list fields
        for field in [
            "steps", "active_energy_burned", "distance_walking_running",
            "flights_climbed", "exercise_time", "workouts",
            "blood_glucose", "blood_pressure_diastolic", "blood_pressure_systolic",
            "heart_rate", "blood_oxygen", "resting_heart_rate",
            "body_temperature", "weight", "respiratory_rate",
            "sleep_in_bed", "sleep_deep", "sleep_light", "sleep_rem", "sleep_awake",
        ]:
            body[field] = []

        for row in daily_fitness.get(day, []):
            ftype = row[0]
            point = {
                "type": ftype,
                "source_name": row[1] or "Apple Health",
                "source_platform": row[2] or "ios",
                "unit": row[3] or "count",
                "value": float(row[4]),
                "start_datetime": row[5].isoformat(),
                "end_datetime": row[6].isoformat(),
            }
            field = fitness_type_map.get(ftype, ftype)
            if field in body:
                body[field].append(point)

        for row in daily_vitals.get(day, []):
            vtype = row[0]
            field = vitals_type_map.get(vtype)
            if field and field in body:
                point = {
                    "type": vtype,
                    "source_name": row[3] or "Apple Health",
                    "source_platform": row[4] or "ios",
                    "unit": "count",
                    "value": float(row[1]),
                    "start_datetime": row[2].isoformat(),
                    "end_datetime": row[2].isoformat(),
                }
                body[field].append(point)

        total_points = sum(
            len(v) for v in body.values() if isinstance(v, list)
        )
        if total_points == 0:
            continue

        resp = await client.post("/patient/fitness/upload", json=body)
        status = "✓" if resp.status_code == 200 else f"✗ {resp.status_code}"
        print(f"  {status} {day}: {total_points} data points")
        if resp.status_code != 200:
            print(f"       {resp.text[:200]}")
        await asyncio.sleep(BATCH_DELAY)


# ---------------------------------------------------------------------------
# LIST-RICH-PATIENTS command
# ---------------------------------------------------------------------------

async def cmd_list_rich(args):
    engine = pg_engine()
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
                SELECT
                    p.patient_id,
                    p.first_name,
                    COALESCE(meal_c.cnt, 0) AS meals,
                    COALESCE(workout_c.cnt, 0) AS workouts,
                    COALESCE(smbg_c.cnt, 0) AS smbg,
                    COALESCE(sleep_c.cnt, 0) AS sleep,
                    COALESCE(mood_c.cnt, 0) AS mood,
                    COALESCE(symptom_c.cnt, 0) AS symptoms,
                    COALESCE(med_c.cnt, 0) AS meds,
                    COALESCE(plan_c.cnt, 0) AS plans
                FROM patients p
                LEFT JOIN LATERAL (
                    SELECT count(*) AS cnt FROM patient_meals WHERE patient_id = p.patient_id
                ) meal_c ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS cnt FROM patient_workouts WHERE patient_id = p.patient_id
                ) workout_c ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS cnt FROM patient_smbgs WHERE patient_id = p.patient_id
                ) smbg_c ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS cnt FROM sleep_checkins WHERE patient_id = p.patient_id
                ) sleep_c ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS cnt FROM mood_entries WHERE patient_id = p.patient_id
                ) mood_c ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS cnt FROM symptom_entries WHERE patient_id = p.patient_id
                ) symptom_c ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS cnt FROM patient_medications WHERE patient_id = p.patient_id AND status = 'active'
                ) med_c ON true
                LEFT JOIN LATERAL (
                    SELECT count(*) AS cnt FROM patient_diet_plans WHERE patient_id = p.patient_id AND status = 'ACTIVE'
                ) plan_c ON true
                ORDER BY (COALESCE(meal_c.cnt,0) + COALESCE(workout_c.cnt,0) +
                          COALESCE(smbg_c.cnt,0) + COALESCE(sleep_c.cnt,0) +
                          COALESCE(mood_c.cnt,0) + COALESCE(symptom_c.cnt,0) +
                          COALESCE(med_c.cnt,0) + COALESCE(plan_c.cnt,0)) DESC
                LIMIT 15
            """)
        )
        results = rows.fetchall()

    await engine.dispose()

    print("\nPatients with most data:\n")
    print(f"{'Patient ID':<40} {'Name':<15} {'Meals':>6} {'Work':>6} {'SMBG':>6} {'Sleep':>6} {'Mood':>6} {'Symp':>6} {'Meds':>6} {'Plans':>6}")
    print("-" * 116)
    for r in results:
        total = sum(r[2:])
        if total == 0:
            continue
        print(
            f"{str(r[0]):<40} {(r[1] or '?'):<15} "
            f"{r[2]:>6} {r[3]:>6} {r[4]:>6} {r[5]:>6} {r[6]:>6} {r[7]:>6} {r[8]:>6} {r[9]:>6}"
        )


# ---------------------------------------------------------------------------
# RESET command
# ---------------------------------------------------------------------------

async def cmd_reset(args):
    state = load_state()
    demo_pid = state.get("patient_id")
    if not demo_pid:
        print("ERROR: No demo patient found. Run 'setup' first.")
        sys.exit(1)

    print(f"\nResetting all data for demo patient {demo_pid}\n")

    engine = pg_engine()

    # -- PostgreSQL tables (CASCADE handles child rows like food_items, sets, etc.)
    pg_tables = [
        ("patient_meals", "patient_id"),
        ("patient_workouts", "patient_id"),
        ("patient_smbgs", "patient_id"),
        ("sleep_checkins", "patient_id"),
        ("mood_entries", "patient_id"),
        ("symptom_entries", "patient_id"),
        ("patient_prescriptions", "patient_id"),
        ("patient_medications", "patient_id"),
        ("patient_diet_plans", "patient_id"),
        ("patient_fitness_plans", "patient_id"),
        ("patient_notifications", "patient_id"),
        # Gamification
        ("xp_ledger", "player_id"),
        ("daily_tasks", "patient_id"),
        ("patient_achievements", "patient_id"),
        ("weekly_quests", "patient_id"),
        ("player_profiles", "patient_id"),
    ]

    async with engine.begin() as conn:
        for table, col in pg_tables:
            try:
                result = await conn.execute(
                    text(f"DELETE FROM {table} WHERE {col} = :pid"),
                    {"pid": demo_pid},
                )
                if result.rowcount > 0:
                    print(f"  Deleted {result.rowcount} rows from {table}")
            except Exception as e:
                print(f"  Skipped {table}: {e}")

    await engine.dispose()

    # -- ClickHouse tables
    try:
        ch = ch_client()
        ch_tables = [
            "aihealth.cgm_data",
            "aihealth.fitness_data",
            "aihealth.vitals_data",
            "aihealth.sleep_data",
        ]
        for table in ch_tables:
            try:
                ch.execute(
                    f"ALTER TABLE {table} DELETE WHERE patient_id = %(pid)s",
                    {"pid": demo_pid},
                    settings={"mutations_sync": 1},
                )
                print(f"  Cleared {table}")
            except Exception as e:
                print(f"  Skipped {table}: {e}")
    except Exception as e:
        print(f"  ClickHouse unavailable: {e}")

    # -- MongoDB collections
    if MONGO_URI:
        try:
            mc = mongo_client()
            db = mc[MONGO_DB]
            mongo_collections = [
                "ai_patient_memory",
                "ai_conversation_turns",
                "ai_thread_summaries",
            ]
            for col_name in mongo_collections:
                result = await db[col_name].delete_many({"patient_id": demo_pid})
                if result.deleted_count > 0:
                    print(f"  Deleted {result.deleted_count} docs from {col_name}")
            mc.close()
        except Exception as e:
            print(f"  MongoDB unavailable: {e}")

    # -- Qdrant vectors
    try:
        from qdrant_client import QdrantClient
        from decouple import config as decouple_config

        qdrant_url = decouple_config("QDRANT_URL", default="")
        qdrant_api_key = decouple_config("QDRANT_API_KEY", default="")
        if qdrant_url:
            qc = QdrantClient(url=qdrant_url, api_key=qdrant_api_key or None, timeout=30)
            collections = qc.get_collections().collections
            for col in collections:
                try:
                    from qdrant_client.models import Filter, FieldCondition, MatchValue
                    qc.delete(
                        collection_name=col.name,
                        points_selector=Filter(
                            must=[FieldCondition(key="patient_id", match=MatchValue(value=demo_pid))]
                        ),
                    )
                    print(f"  Cleared Qdrant collection: {col.name}")
                except Exception:
                    pass
            qc.close()
    except Exception as e:
        print(f"  Qdrant unavailable: {e}")

    print("\n✓ Reset complete! You can now run 'replay' again.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

ALL_DATA_TYPES = [
    "profile", "meals", "workouts", "smbg", "sleep", "mood", "symptoms",
    "prescriptions", "diet_plans", "fitness_plans",
    "cgm", "fitness", "memories",
]


def main():
    parser = argparse.ArgumentParser(description="Demo environment seeder")
    sub = parser.add_subparsers(dest="command")

    # setup
    p_setup = sub.add_parser("setup", help="Create demo facility, provider, patient")
    p_setup.add_argument("--server-url", default="http://localhost:8000")

    # replay
    p_replay = sub.add_parser("replay", help="Replay source patient data into demo patient")
    p_replay.add_argument("--source-patient-id", required=True)
    p_replay.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p_replay.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    p_replay.add_argument("--server-url", default="http://localhost:8000")
    p_replay.add_argument(
        "--data-types",
        nargs="+",
        default=ALL_DATA_TYPES,
        choices=ALL_DATA_TYPES,
        help="Which data types to replay (default: all)",
    )

    # list-rich-patients
    sub.add_parser("list-rich-patients", help="List patients with the most data")

    # reset
    sub.add_parser("reset", help="Wipe all demo patient data so replay can run cleanly")

    args = parser.parse_args()

    if args.command == "setup":
        asyncio.run(cmd_setup(args))
    elif args.command == "replay":
        asyncio.run(cmd_replay(args))
    elif args.command == "list-rich-patients":
        asyncio.run(cmd_list_rich(args))
    elif args.command == "reset":
        asyncio.run(cmd_reset(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
