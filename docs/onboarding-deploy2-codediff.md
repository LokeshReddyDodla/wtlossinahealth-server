# Deploy 2 — Code changes (strip dual-write, single source of truth)

Apply this PR **at the same time** as `patient_profile_v1_drop_legacy.py` (the destructive migration). The code must stop writing to legacy columns the moment they're dropped.

Order: merge this PR → apply migration → done. Or apply migration first if your deploy pipeline is sequenced that way — either order works as long as both happen close together.

---

## 1. `lib/services/patient_profile_service.py` — strip dual-write

### `_apply_identity_and_body`

Remove the `locale` and `height`/`weight`/`waist` legacy writes:

```diff
         patient.timezone = data.timezone
-        patient.locale = data.timezone  # dual-write during soak
         if data.occupation is not None:
             patient.occupation = data.occupation
         patient.height_cm = data.height_cm
         patient.weight_kg = data.weight_kg
-        patient.height = data.height_cm  # legacy dual-write
-        patient.weight = data.weight_kg  # legacy dual-write
         if data.waist_cm is not None:
             patient.waist_cm = data.waist_cm
-            patient.waist = data.waist_cm  # legacy dual-write
```

### `_apply_smoking_habit`

Remove the `smoke_status` legacy line:

```diff
         entity.status = section.status
-        entity.smoke_status = section.status == "CURRENT"  # legacy dual-write
         entity.cigarettes_per_day = section.cigarettes_per_day
```

### `_apply_alcohol_consumption`

Remove the two legacy lines:

```diff
         entity.status = section.status
-        entity.consume_alcohol = section.status != "NEVER"  # legacy dual-write
         entity.frequency = section.frequency
         entity.drinks_per_session = section.drinks_per_session
-        entity.quantity = (
-            str(section.drinks_per_session)
-            if section.drinks_per_session is not None
-            else None
-        )  # legacy dual-write
         entity.type_of_alcohol = list(section.type_of_alcohol) or None
```

### `_apply_sleep_habit`

Remove the legacy duration line:

```diff
         entity.average_sleep_hours = section.average_sleep_hours
-        entity.average_sleep_duration = (
-            str(section.average_sleep_hours)
-            if section.average_sleep_hours is not None
-            else None
-        )  # legacy dual-write
         entity.bed_time = section.bed_time
```

---

## 2. SQLAlchemy models — drop legacy column definitions

### `lib/models/patient.py`
```diff
-    height = Column(Float)
-    waist = Column(Float)
-    weight = Column(Float)
     height_cm = Column(Float, nullable=True)
     weight_kg = Column(Float, nullable=True)
     waist_cm = Column(Float, nullable=True)
-    locale = Column(String(50), nullable=True, default="Asia/Kolkata")
     timezone = Column(String(64), nullable=True)
```

### `lib/models/patient_smoking_habit.py`
```diff
-    smoke_status = Column(Boolean)
     status = Column(String(20), nullable=True)
```
Also remove `Boolean` from the imports if no longer used.

### `lib/models/patient_alcohol_consumption.py`
```diff
-    consume_alcohol = Column(Boolean)
     status = Column(String(20), nullable=True)
     frequency = Column(String(50), nullable=True)
-    quantity = Column(String(50), nullable=True)
     drinks_per_session = Column(Integer, nullable=True)
```

### `lib/models/patient_sleep_habit.py`
```diff
-    average_sleep_duration = Column(String, nullable=True)
     average_sleep_hours = Column(Float, nullable=True)
```

---

## 3. Pydantic response schemas — expose clean fields only

These currently still have the legacy fields. Replace with the new ones.

### `lib/schemas/patient.py` — `PatientBase`
```diff
-    locale: Optional[str] = None
+    timezone: Optional[str] = None
+    occupation: Optional[str] = None
```
And rename `height/weight/waist` consumers if you want unitful names (separate task — purely additive cosmetic; no DB column rename required for this phase).

### `lib/schemas/patient_smoking_habit.py`
```diff
 class PatientSmokingHabitBase(BaseModel):
-    smoke_status: bool
+    status: Optional[Literal["NEVER", "CURRENT", "FORMER"]] = None
     years_of_smoking: Optional[float] = None
     cigarettes_per_day: Optional[int] = None
     quit_years_ago: Optional[int] = None
```

### `lib/schemas/patient_alcohol_consumption.py`
```diff
 class PatientAlcoholConsumptionBase(BaseModel):
-    consume_alcohol: bool
+    status: Optional[Literal["NEVER", "OCCASIONAL", "REGULAR", "FORMER"]] = None
     frequency: Optional[str] = None
-    quantity: Optional[str] = None
+    drinks_per_session: Optional[int] = None
     type_of_alcohol: Optional[List[str]] = None
```

### `lib/schemas/patient_sleep_habit.py`
```diff
 class PatientSleepHabitBase(BaseModel):
     sleep_quality: str
     wake_up_fresh: Optional[bool] = None
     drowsy_day: Optional[bool] = None
-    average_sleep_duration: Optional[str] = None
+    average_sleep_hours: Optional[float] = None
     wake_up_time: Optional[datetime_time] = None
     bed_time: Optional[datetime_time] = None
```

---

## 4. Legacy endpoints — decision time

The legacy endpoints still write to legacy columns:

- `PUT  /patient/profile/basic`        — writes `locale`
- `PATCH /patient/profile/lifestyle`   — writes `smoke_status`, `consume_alcohol`, `quantity`, `average_sleep_duration`
- `PATCH /patient/profile/medical_history`

Two choices when Deploy 2 lands:

**A. Delete them.** Frontend uses only `/v1/patients/onboarding`. Cleanest.

**B. Refactor them** to write the clean columns too. Heavier change but keeps them as edit endpoints (post-onboarding profile edits).

If you want partial profile-edit endpoints, do (B) — but write them fresh under `/v1/patients/profile/*` with the clean schemas. Don't keep the old ones limping.

---

## Pre-flight checklist

- [ ] `docs/onboarding-soak-verification.sql` returns clean counts
- [ ] Postgres snapshot taken in the last 30 min
- [ ] This code PR is merged to main
- [ ] `patient_profile_v1_drop_legacy` is the next migration to run
- [ ] Deploy
- [ ] Smoke test: POST /v1/patients/onboarding with a test patient → 200
- [ ] Smoke test: GET patient → only new fields present
