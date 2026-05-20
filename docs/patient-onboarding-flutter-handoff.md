# Patient Onboarding — Flutter Integration

Hand-off doc for the chat-style onboarding flow. Server-side is complete on `feat/support-tickets`. Everything below is live; you can integrate now.

---

## TL;DR

Three endpoints. One canonical shape. Patch-as-you-go.

| Method | Path | When to call |
|---|---|---|
| `GET`   | `/v1/patients/profile`    | App launch + after every successful PATCH. Hydrates local state from server-truth. |
| `PATCH` | `/v1/patients/profile`    | Debounced sync from the chat flow. Send any subset of fields. |
| `POST`  | `/v1/patients/onboarding` | Optional — strict all-at-once. New flow doesn't need it. |

All three return `CorePatientProfile` (same shape). Reconciliation is trivial.

---

## 1. The three endpoints

### `GET /v1/patients/profile`

Auth: patient JWT (same auth dependency as the existing `/patient/profile`).

Returns the current patient's full profile. No query params. Eagerly loads every section (daily_activity, eating_habit, alcohol_consumption, smoking_habit, sleep_habit, food_allergies, drug_allergies, diabetic_history, reproductive_health, family_diabetic_histories, medical_histories, eating_habit.meal_timings, eating_habit.diet_preferences) plus care_providers, package_assignments, health_facility.

**Response shape**: `SuccessResponse<CorePatientProfile>` — see section 3.

### `PATCH /v1/patients/profile`

Auth: patient JWT.

Body: any subset of the onboarding shape (section 3). Every field is Optional.

**Merge rules:**
| Body content | Server behavior |
|---|---|
| Field absent from body | Don't touch existing value |
| Top-level scalar present | Overwrite |
| Top-level nested object present, only some inner fields included | Merge — only the inner fields you sent overwrite; the rest preserved |
| Top-level list present | **Replace** the whole list |
| Empty body `{}` | Valid no-op. Useful as "ping + reconcile". Still recomputes `profile_completion` and returns fresh profile. |

**Response**: `SuccessResponse<CorePatientProfile>` — full reconciled state. Push it back into `ProfileViewModel.profileResponse` directly.

### `POST /v1/patients/onboarding` (optional)

Strict variant — same shape but every required field must be present. Returns `SuccessResponse<CorePatientProfile>`. Use only if you want one-shot onboarding. The new chat flow uses PATCH exclusively, so you can ignore this.

---

## 2. profile_completion

The server computes this on every PATCH from actual field presence — no separate "finalize" call needed.

```json
"profile_completion": {
  "basic":           { "is_complete": true,  "is_mandatory": true },
  "lifestyle":       { "is_complete": false, "is_mandatory": true },
  "medical_history": { "is_complete": false, "is_mandatory": true }
}
```

Server rules:
- **basic** = `first_name` && `gender` && `dob` && (`height_cm` || `height`) && (`weight_kg` || `weight`)
- **lifestyle** = `daily_activity` && `alcohol_consumption` && `smoking_habit` && `sleep_habit` && `eating_habit` (all five sections exist as rows)
- **medical_history** = `diabetic_history` exists

Read these flags to gate UX (show "complete profile" CTA, route to onboarding flow on launch, etc.). They flip back automatically if a user clears a required field.

---

## 3. Request / Response shape

The same nested JSON works for both PATCH (any subset) and POST onboarding (all required fields). Comments show enum vocabularies.

```jsonc
{
  // ─── IDENTITY ─────────────────────────────────────────────────────────
  "first_name": "Dfgsdg",                // required for onboarding completion
  "last_name": "Doe",                    // optional
  "email": "dgredg@g.com",               // optional
  "phone_number": "+919876543210",       // optional (already set at OTP signup)
  "gender": "MALE",                      // MALE | FEMALE | OTHER | PREFER_NOT_TO_SAY
  "dob": "2001-05-12",                   // YYYY-MM-DD
  "profile_picture": null,               // optional URL
  "timezone": "Asia/Kolkata",            // IANA. NOT "locale".
  "occupation": "Software Engineer",     // optional

  // ─── BODY (units in the name) ─────────────────────────────────────────
  "height_cm": 170.0,                    // 30..300
  "weight_kg": 70.0,                     // 2..500
  "waist_cm": 84.0,                      // optional, 20..300
  "hip_cm": null,                        // optional, 20..300

  // ─── DAILY ACTIVITY ───────────────────────────────────────────────────
  "daily_activity": {
    "activity_level": "VERY_ACTIVE"      // SEDENTARY | LIGHT | MODERATE | ACTIVE | VERY_ACTIVE
  },

  // ─── EATING HABIT ─────────────────────────────────────────────────────
  "eating_habit": {
    "meals_per_day": 3,                  // 0..10
    "snacks_count": 1,                   // 0..10
    "diet_preferences": ["VEG"],         // list (replaces whole when present)
    // VEG | NON_VEG | VEGAN | EGGETARIAN | JAIN
    // | KETO | LOW_CARB | DIABETIC_FRIENDLY | HALAL | KOSHER
    "diet_preferences_detail": "Greg",   // optional free text
    "cuisine_preferences": ["ITALIAN","MEXICAN"],  // list (replaces whole)
    "meal_timings": [                    // list (replaces whole)
      { "meal_type": "BREAKFAST", "time": "08:00" },
      { "meal_type": "LUNCH",     "time": "13:00" },
      { "meal_type": "DINNER",    "time": "20:00" }
      // meal_type: BREAKFAST | LUNCH | DINNER | SNACK_AM | SNACK_PM
    ]
  },

  // ─── ALLERGIES (lists — replace whole) ────────────────────────────────
  "food_allergies": [
    {
      "name": "TREE_NUTS",               // DAIRY | SHELLFISH | NUTS | TREE_NUTS | PEANUTS
                                         //  | EGGS | GLUTEN | SOY | FISH | OTHER
      "name_other": null,                // free text when name=OTHER
      "severity": "MODERATE"             // optional: MILD | MODERATE | SEVERE
    }
  ],
  "drug_allergies": [
    {
      "name": "PENICILLIN",              // PENICILLIN | NSAIDS | SULFA | ASPIRIN | OPIOIDS | OTHER
      "name_other": null,
      "reaction": "Rash + swelling"      // optional free text
    }
  ],

  // ─── DIABETIC HISTORY ─────────────────────────────────────────────────
  "diabetic_history": {
    "type_of_diabetes": "T2",            // NONE | PRE | T1 | T2 | GESTATIONAL | LADA | MODY | OTHER
    "years_with_diabetes": 5.0,          // float
    "diagnosed_at": "2020-08-01"         // optional date (more precise than years)
  },

  // ─── FAMILY DIABETIC (list — replaces whole) ──────────────────────────
  "family_diabetic_histories": [
    {
      "family_member": "GRANDFATHER_MATERNAL",
      // FATHER | MOTHER | BROTHER | SISTER | SON | DAUGHTER
      // | GRANDFATHER_PATERNAL | GRANDMOTHER_PATERNAL
      // | GRANDFATHER_MATERNAL | GRANDMOTHER_MATERNAL | UNCLE | AUNT
      "type_of_diabetes": "T2",          // optional: T1 | T2 | GESTATIONAL | OTHER | UNKNOWN
      "years_with_diabetes": 20.0
    }
  ],

  // ─── MEDICAL HISTORY (list — replaces whole) ──────────────────────────
  "medical_histories": [
    {
      "condition": "HEART_DISEASE",
      // HYPERTENSION | HYPOTHYROIDISM | HYPERTHYROIDISM | PCOS
      // | KIDNEY_DISEASE | LIVER_DISEASE | HEART_DISEASE | LUNG_DISEASE
      // | STROKE | CANCER | ASTHMA | DEPRESSION | ANXIETY | SLEEP_APNEA | OTHER
      "condition_other": null,           // free text when condition=OTHER
      "status": "CHRONIC",               // optional: ACTIVE | RESOLVED | CHRONIC
      "duration_years": 3.0,
      "started_at": null,                // optional precise date
      "details": "Example text"
    }
  ],

  // ─── ALCOHOL ──────────────────────────────────────────────────────────
  "alcohol_consumption": {
    "status": "REGULAR",                 // NEVER | OCCASIONAL | REGULAR | FORMER
    "frequency": "MONTHLY",              // optional: DAILY | WEEKLY | MONTHLY | RARELY | NEVER
    "drinks_per_session": 2,             // optional int
    "type_of_alcohol": ["WINE"],         // list (replaces whole): BEER | WINE | SPIRITS | COCKTAILS | OTHER
    "quit_years_ago": null               // optional, set when status=FORMER
  },

  // ─── SMOKING ──────────────────────────────────────────────────────────
  "smoking_habit": {
    "status": "CURRENT",                 // NEVER | CURRENT | FORMER
    "smoke_type": ["CIGARETTES"],        // list (replaces whole): CIGARETTES | CIGARS | VAPE | HOOKAH | OTHER
    "cigarettes_per_day": 5,             // optional
    "years_of_smoking": 5.0,             // optional float (1.5 yrs is fine)
    "quit_years_ago": null               // optional
  },

  // ─── SLEEP ────────────────────────────────────────────────────────────
  "sleep_habit": {
    "sleep_quality": "AVERAGE",          // POOR | FAIR | AVERAGE | GOOD | EXCELLENT
    "average_sleep_hours": 7.0,          // optional float, 0..24
    "bed_time": "23:00",                 // optional HH:MM
    "wake_up_time": "07:00",             // optional HH:MM
    "wake_up_fresh": true,               // optional
    "drowsy_day": true,                  // optional
    "snores": false                      // optional
  },

  // ─── REPRODUCTIVE HEALTH (omit when gender != FEMALE) ─────────────────
  "reproductive_health": {
    "is_pregnant": false,                // optional
    "pregnancy_weeks": null,             // optional, 0..45
    "menopause_status": "NOT_APPLICABLE", // optional: PRE | PERI | POST | NOT_APPLICABLE
    "period_regularity": "REGULAR",       // optional: REGULAR | IRREGULAR | NOT_APPLICABLE
    "uses_contraception": false           // optional
  }
}
```

---

## 4. Legacy fields in the response

GET responses include **both** legacy fields and new fields side-by-side during the soak window. Read whichever your code is ready for. Migrate field-by-field at your pace. Once your release is fully on new fields, we drop legacy in a separate cleanup (Deploy 2 — server-side).

| New field | Legacy field still present | Notes |
|---|---|---|
| `timezone` | `locale` | IANA name in both during soak |
| `height_cm` / `weight_kg` / `waist_cm` | `height` / `weight` / `waist` | Same values, just unit-suffixed |
| `hip_cm` | (no legacy equiv) | Net-new |
| `occupation` | (no legacy equiv) | Net-new |
| `smoking_habit.status` (enum) | `smoking_habit.smoke_status` (bool) | `CURRENT` → `true`, `NEVER`/`FORMER` → `false` |
| `smoking_habit.smoke_type` (list) | (no legacy equiv) | Net-new |
| `alcohol_consumption.status` (enum) | `alcohol_consumption.consume_alcohol` (bool) | `NEVER` → `false`, else `true` |
| `alcohol_consumption.drinks_per_session` (int) | `alcohol_consumption.quantity` (string) | Same value, string vs int |
| `alcohol_consumption.quit_years_ago` | (no legacy equiv) | Net-new |
| `sleep_habit.average_sleep_hours` (float) | `sleep_habit.average_sleep_duration` (string) | Same value, string vs float |
| `sleep_habit.snores` | (no legacy equiv) | Net-new |
| `diabetic_history.diagnosed_at` | (no legacy equiv) | Net-new |
| `family_diabetic_histories[].type_of_diabetes` | (no legacy equiv) | Net-new |
| `medical_histories[].condition_other`, `status`, `started_at` | (no legacy equiv) | Net-new |
| `food_allergies[].name` (enum) + `name_other` + `severity` | `food_allergies[].allergy_name` (free string) | Backfilled — if it matched enum, `name=<enum>`; else `name="OTHER"` + `name_other=<original>` |
| `drug_allergies[].name` (enum) + `name_other` + `reaction` | `drug_allergies[].allergy_name` (free string) | Same pattern as food |
| `eating_habit.dietary_preferences` (list) + `diet_preferences_detail` | `eating_habit.diet_preferences` (single object: `{preference, detail}`) | Legacy holds first item only |
| `reproductive_health.*` (new nested section) | `diabetic_history.is_pregnant`, `diabetic_history.pregnancy_weeks` | Pregnancy data also written to reproductive_health going forward; legacy diabetic fields kept in sync |

Pick the new field. Each of them is the future source of truth.

---

## 5. Chat-flow integration pattern (matches your existing GetX + GetStorage + Dio stack)

The plan you outlined is correct. Here's the canonical version mapped to the endpoints above.

### State layers

```
┌─────────────────────────────────────────────────────────────────┐
│  ProfileSetupViewModel  (in-memory Rx — instant UI)             │
│    answers : RxMap        ← updated on every chat answer        │
│    _dirtySteps : Set      ← which sections need flushing        │
│    isSyncing  : RxBool                                           │
│    hasUnsynced : RxBool                                          │
│    syncError  : RxnString                                        │
└─────────────────────────────────────────────────────────────────┘
                          │ debounced 1.5s
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  ProfileSetupRepository.patchProfile(body)                      │
│    → PATCH /v1/patients/profile                                  │
│    Response → push into ProfileViewModel.profileResponse         │
└─────────────────────────────────────────────────────────────────┘
                          │ on failure
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  OnboardingStateStore  (GetStorage — retry queue only)          │
│    Holds last-failed payload                                     │
│    Drains on next successful PATCH after relaunch                │
└─────────────────────────────────────────────────────────────────┘
```

### Lifecycle

| Event | Action |
|---|---|
| App launch | `GET /v1/patients/profile` → hydrate `ProfileViewModel.profileResponse` → prefill local state from it. If `profile_completion.basic.is_complete` is false, route to onboarding flow at the first gap. |
| User answers a question | `_commitAnswer(step, value)` → updates `answers` Rx → adds step to `_dirtySteps` → resets debounce timer. |
| 1.5s of inactivity | Debounce fires → `_flushToBackend()` → build partial body from `_dirtySteps` → PATCH. |
| Screen transition (next/prev) | Force-flush — `_flushToBackend()` directly, skip debounce. |
| App backgrounded (`WidgetsBindingObserver.didChangeAppLifecycleState(paused)`) | Force-flush. |
| Reaching `isFinished` | Force-flush. No separate "finalize" call needed — server already marked sections complete. |
| PATCH success | Push response into `ProfileViewModel.profileResponse`, clear `_dirtySteps`, set `hasUnsynced=false`. |
| PATCH failure (network/5xx) | Store payload in `OnboardingStateStore` retry slot, set `syncError`. Keep `_dirtySteps` populated. |
| Race — answer arrives while PATCH in-flight | Don't fire second PATCH. Keep growing `_dirtySteps`. When in-flight returns, if `_dirtySteps` non-empty, fire again. |

### Building the partial body

```dart
Map<String, dynamic> _buildPatchFor(Set<String> dirtySteps) {
  final body = <String, dynamic>{};

  // Scalars — only include if their step is dirty
  if (dirtySteps.contains('gender')) body['gender'] = answers['gender'];
  if (dirtySteps.contains('dob'))    body['dob']    = answers['dob'];
  if (dirtySteps.contains('height')) body['height_cm'] = answers['height_cm'];
  // …

  // Nested sections — partial merge
  if (dirtySteps.any((s) => s.startsWith('smoking_'))) {
    body['smoking_habit'] = {
      if (dirtySteps.contains('smoking_status'))     'status': answers['smoking_status'],
      if (dirtySteps.contains('smoking_cigarettes')) 'cigarettes_per_day': answers['smoking_cigarettes'],
      // …only the inner fields the user touched
    };
  }

  // Lists — if ANY step touching the list is dirty, send the WHOLE list
  if (dirtySteps.any((s) => s.startsWith('food_allergy_'))) {
    body['food_allergies'] = answers['food_allergies'];  // full list
  }
  if (dirtySteps.any((s) => s.startsWith('meal_timing_'))) {
    body['eating_habit'] ??= {};
    body['eating_habit']['meal_timings'] = answers['meal_timings'];  // full list
  }

  return body;
}
```

Key rule: **lists go whole, scalars go surgical.** Backend will merge nested objects, replace lists.

### Sync indicator UI

Three states:
- `isSyncing` → "Saving…"
- `hasUnsynced && !isSyncing && syncError == null` → idle queue waiting for debounce — show nothing or "Auto-saved"
- `syncError != null` → "Offline — will sync when back"
- After a successful flush → "Saved ✓" for 2 seconds, then fades

---

## 6. Examples

### Example A — First-time user, mid-chat, just answered "what's your gender?"

PATCH body:
```json
{ "gender": "FEMALE" }
```

Response: full profile, with `gender: "FEMALE"` and `profile_completion.basic.is_complete: false` (other required fields still empty).

### Example B — User completes the mandatory basic set

After 5 chat answers, accumulated dirty steps flush together:
```json
{
  "first_name": "Asha",
  "gender": "FEMALE",
  "dob": "1993-04-12",
  "height_cm": 162,
  "weight_kg": 58,
  "timezone": "Asia/Kolkata"
}
```

Response includes `profile_completion.basic.is_complete: true`. Frontend can dismiss "incomplete profile" banner.

### Example C — User adds 2 food allergies, then removes 1

After both adds, dirty set has `food_allergy_*` markers; flush body:
```json
{ "food_allergies": [{ "name": "DAIRY" }, { "name": "TREE_NUTS", "severity": "MODERATE" }] }
```

User then removes DAIRY in the same session; next flush:
```json
{ "food_allergies": [{ "name": "TREE_NUTS", "severity": "MODERATE" }] }
```

Server replaces the whole list. DAIRY is gone.

### Example D — Existing user edits one thing (height)

```json
{ "height_cm": 165 }
```

Response: full profile reflecting new height. Everything else untouched.

### Example E — Ping & reconcile

```json
{}
```

Valid. Server recomputes `profile_completion`, returns fresh profile. Useful if you suspect local state drifted from server.

---

## 7. Validation errors

422 response on enum violations, range violations, type mismatches. Body looks like FastAPI's standard:
```json
{
  "detail": [
    {
      "loc": ["body", "smoking_habit", "status"],
      "msg": "Input should be 'NEVER', 'CURRENT' or 'FORMER'",
      "type": "literal_error"
    }
  ]
}
```

Field-level errors in `loc[]`. Surface to user or fix client-side. Use Dart enums + `.name` to avoid these entirely.

---

## 8. What you can safely delete from your code

Once you're on the new endpoints:
- `submitOnboarding` POST call from the chat finish step → not needed; PATCH already saved everything
- `FinishedFooter` "Save changes" button → not needed; auto-saved already
- `OnboardingStateStore` as the in-progress source of truth → demoted to retry queue only
- Bootstrap "saved local snapshot vs backend prefill" priority logic → server is truth, local fills the gap during the session only

Old endpoints (`PUT /patient/profile/basic`, `PATCH /patient/profile/lifestyle`, `PATCH /patient/profile/medical_history`) still work — stop calling them when ready, we delete them in a later cleanup PR.

---

## 9. Timeline / what's next on backend side

1. **Now** — new endpoints live in `feat/support-tickets`. Both legacy + new fields returned on GETs.
2. **You ship** the Flutter side calling PATCH + GET. Soak begins.
3. **Soak window (1-2+ weeks)** — both old + new continue to work. We monitor parity. You can roll the new app version out gradually.
4. **Deploy 2 (backend cleanup)** — after you signal that 100% of installs are on new fields, we strip dual-write, drop legacy DB columns, remove legacy fields from response schemas. No frontend work required, just stop expecting legacy keys in responses.

---

## Open items to confirm with backend before coding

None — every point in your plan is supported as-is:
- ✅ PATCH `/v1/patients/profile`
- ✅ Returns full reconciled `CorePatientProfile`
- ✅ POST `/v1/patients/onboarding` stays optional, not retired (you can ignore it)
- ✅ Lists replace whole; scalars/nested-objects merge
- ✅ `profile_completion` server-computed
- ✅ Empty body is a valid no-op

Go.
