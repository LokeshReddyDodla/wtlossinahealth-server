# Patient Onboarding — Flutter Integration

Hand-off doc for the chat-style onboarding flow. Server is ready on `feat/support-tickets`.

---

## TL;DR

Three endpoints. One shape. Patch-as-you-go.

| Method | Path | When |
|---|---|---|
| `GET`   | `/v1/patients/profile`    | App launch + after every successful PATCH. Hydrates local state from server. |
| `PATCH` | `/v1/patients/profile`    | Debounced sync from chat answers. Send any subset of fields. |
| `POST`  | `/v1/patients/onboarding` | Optional — strict all-at-once. Chat flow doesn't need it. |

All three return the same response shape. Reconciliation is trivial.

---

## 1. The endpoints

### `GET /v1/patients/profile`

- **Auth**: patient JWT.
- **Body**: none.
- **Returns**: full patient profile (shape in section 3).

Call on app launch to hydrate. Re-read after every PATCH response (the response already contains the reconciled state, but a fresh GET is also fine).

### `PATCH /v1/patients/profile`

- **Auth**: patient JWT.
- **Body**: any subset of the profile shape. Every field optional.
- **Returns**: full reconciled profile.

**Merge rules:**

| Body content | Server behavior |
|---|---|
| Field absent from body | Don't touch existing value |
| Top-level scalar present | Overwrite |
| Top-level nested object present, only some inner fields included | Merge — only the inner fields you sent overwrite; the rest preserved |
| Top-level list present | **Replace** the whole list |
| Empty body `{}` | Valid no-op. Returns fresh profile + recomputed `profile_completion`. |

Push the response into `ProfileViewModel.profileResponse` after each call.

### `POST /v1/patients/onboarding`

Strict, all-at-once version. Requires every mandatory field at once. The new chat flow uses PATCH exclusively, so you can ignore this endpoint.

---

## 2. `profile_completion`

The server computes this on every PATCH from actual field presence. No "finalize" call needed.

```json
"profile_completion": {
  "basic":           { "is_complete": true,  "is_mandatory": true },
  "lifestyle":       { "is_complete": false, "is_mandatory": true },
  "medical_history": { "is_complete": false, "is_mandatory": true }
}
```

Server rules:
- **basic** complete when `first_name && gender && dob && height_cm && weight_kg`
- **lifestyle** complete when all five sections exist: `daily_activity`, `eating_habit`, `alcohol_consumption`, `smoking_habit`, `sleep_habit`
- **medical_history** complete when `diabetic_history` exists

Read these flags to gate UX (show "complete profile" CTA, route to onboarding on launch, etc.). They flip back automatically if a user clears a required field.

---

## 3. The shape

Same nested JSON for both PATCH (any subset) and POST onboarding (all required fields). Comments show enum vocabularies and which fields are required for completion.

```jsonc
{
  // ─── IDENTITY ─────────────────────────────────────────────────────────
  "first_name": "Asha",                  // required for basic.is_complete
  "last_name": "Doe",                    // optional
  "email": "asha@example.com",           // optional
  "phone_number": "+919876543210",       // optional (set at OTP signup)
  "gender": "FEMALE",                    // MALE | FEMALE | OTHER | PREFER_NOT_TO_SAY
  "dob": "1993-04-12",                   // YYYY-MM-DD
  "profile_picture": null,               // optional URL
  "timezone": "Asia/Kolkata",            // required, IANA
  "occupation": "Software Engineer",     // optional

  // ─── BODY ─────────────────────────────────────────────────────────────
  "height_cm": 162.0,                    // required, 30..300
  "weight_kg": 58.0,                     // required, 2..500
  "waist_cm": 78.0,                      // optional, 20..300
  "hip_cm": 92.0,                        // optional, 20..300

  // ─── DAILY ACTIVITY ───────────────────────────────────────────────────
  "daily_activity": {
    "activity_level": "MODERATE"         // SEDENTARY | LIGHT | MODERATE | ACTIVE | VERY_ACTIVE
  },

  // ─── EATING HABIT ─────────────────────────────────────────────────────
  "eating_habit": {
    "meals_per_day": 3,                  // 0..10
    "snacks_count": 1,                   // 0..10
    "diet_preferences": ["VEG"],         // list (replaces whole)
    // VEG | NON_VEG | VEGAN | EGGETARIAN | JAIN
    // | KETO | LOW_CARB | DIABETIC_FRIENDLY | HALAL | KOSHER
    "diet_preferences_detail": null,     // optional free text
    "cuisine_preferences": ["ITALIAN","INDIAN"],  // list (replaces whole)
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
    "years_with_diabetes": 5.0,          // optional float
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
      "years_with_diabetes": 20.0        // optional float
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
      "details": "Example text"          // optional free text
    }
  ],

  // ─── ALCOHOL ──────────────────────────────────────────────────────────
  "alcohol_consumption": {
    "status": "OCCASIONAL",              // NEVER | OCCASIONAL | REGULAR | FORMER
    "frequency": "MONTHLY",              // optional: DAILY | WEEKLY | MONTHLY | RARELY | NEVER
    "drinks_per_session": 2,             // optional int
    "type_of_alcohol": ["WINE"],         // list (replaces whole): BEER | WINE | SPIRITS | COCKTAILS | OTHER
    "quit_years_ago": null               // optional, set when status=FORMER
  },

  // ─── SMOKING ──────────────────────────────────────────────────────────
  "smoking_habit": {
    "status": "NEVER",                   // NEVER | CURRENT | FORMER
    "smoke_type": [],                    // list (replaces whole): CIGARETTES | CIGARS | VAPE | HOOKAH | OTHER
    "cigarettes_per_day": null,          // optional
    "years_of_smoking": null,            // optional float
    "quit_years_ago": null               // optional
  },

  // ─── SLEEP ────────────────────────────────────────────────────────────
  "sleep_habit": {
    "sleep_quality": "GOOD",             // POOR | FAIR | AVERAGE | GOOD | EXCELLENT
    "average_sleep_hours": 7.0,          // optional float, 0..24
    "bed_time": "23:00",                 // optional HH:MM
    "wake_up_time": "07:00",             // optional HH:MM
    "wake_up_fresh": true,               // optional
    "drowsy_day": false,                 // optional
    "snores": false                      // optional
  },

  // ─── REPRODUCTIVE HEALTH (omit when gender != FEMALE) ─────────────────
  "reproductive_health": {
    "is_pregnant": false,                // optional
    "pregnancy_weeks": null,             // optional, 0..45
    "menopause_status": "PRE",           // optional: PRE | PERI | POST | NOT_APPLICABLE
    "period_regularity": "REGULAR",      // optional: REGULAR | IRREGULAR | NOT_APPLICABLE
    "uses_contraception": false          // optional
  }
}
```

---

## 4. Chat-flow integration pattern

Matches your stack — GetX + GetStorage + Dio + NetworkApiServices. No new packages.

### State layers

```
┌─────────────────────────────────────────────────────────────────┐
│  ProfileSetupViewModel  (in-memory Rx — instant UI)             │
│    answers : RxMap                                               │
│    _dirtySteps : Set<String>                                     │
│    isSyncing : RxBool                                            │
│    hasUnsynced : RxBool                                          │
│    syncError : RxnString                                         │
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
| App launch | `GET /v1/patients/profile` → hydrate `ProfileViewModel.profileResponse` → prefill local state. If `profile_completion.basic.is_complete` is false, route to onboarding flow at the first gap. |
| User answers a question | Update `answers` Rx → add step to `_dirtySteps` → reset 1.5s debounce timer. |
| 1.5s of inactivity | Debounce fires → build partial body from `_dirtySteps` → PATCH. |
| Screen transition (next / prev) | Force-flush, skip debounce. |
| App backgrounded (`didChangeAppLifecycleState(paused)`) | Force-flush. |
| Reaching `isFinished` | Force-flush. No separate "finalize" call. |
| PATCH success | Push response into `ProfileViewModel.profileResponse`, clear `_dirtySteps`, set `hasUnsynced=false`. |
| PATCH failure (network / 5xx) | Store payload in `OnboardingStateStore` retry slot, set `syncError`. Keep `_dirtySteps`. |
| Race — answer arrives while PATCH in-flight | Don't fire a second PATCH. Keep growing `_dirtySteps`. When in-flight returns successfully, fire again immediately if dirty set non-empty. |

### Building the partial body

```dart
Map<String, dynamic> _buildPatchFor(Set<String> dirtySteps) {
  final body = <String, dynamic>{};

  // Scalars — only include if their step is dirty
  if (dirtySteps.contains('gender')) body['gender'] = answers['gender'];
  if (dirtySteps.contains('dob'))    body['dob']    = answers['dob'];
  if (dirtySteps.contains('height')) body['height_cm'] = answers['height_cm'];
  // …

  // Nested sections — partial merge (send only inner fields the user touched)
  if (dirtySteps.any((s) => s.startsWith('smoking_'))) {
    body['smoking_habit'] = {
      if (dirtySteps.contains('smoking_status'))     'status': answers['smoking_status'],
      if (dirtySteps.contains('smoking_cigarettes')) 'cigarettes_per_day': answers['smoking_cigarettes'],
      // …
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

Key rule: **lists go whole, scalars go surgical.**

### Sync indicator UI

- `isSyncing` → "Saving…"
- After success → "Saved ✓" (auto-fades after 2s)
- `syncError != null` → "Offline — will sync when back"

---

## 5. Worked examples

### Example A — Mid-chat, just answered "what's your gender?"

PATCH body:
```json
{ "gender": "FEMALE" }
```

Response: full profile with `gender: "FEMALE"`, `profile_completion.basic.is_complete: false` (other required fields still empty).

### Example B — Completing the mandatory basic set

After several chat answers, accumulated dirty steps flush together:
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

Response: `profile_completion.basic.is_complete: true`. Dismiss any "incomplete profile" banner.

### Example C — User adds 2 food allergies, then removes 1

After both adds (debounced flush):
```json
{ "food_allergies": [{ "name": "DAIRY" }, { "name": "TREE_NUTS", "severity": "MODERATE" }] }
```

User removes DAIRY; next flush:
```json
{ "food_allergies": [{ "name": "TREE_NUTS", "severity": "MODERATE" }] }
```

Server replaces the whole list. DAIRY is gone.

### Example D — Existing user changes one thing

```json
{ "height_cm": 165 }
```

Response: full profile reflecting the new height. Everything else untouched.

### Example E — Ping & reconcile

```json
{}
```

Valid. Server recomputes `profile_completion` and returns fresh profile. Use if you suspect local state has drifted.

---

## 6. Validation errors

`422 Unprocessable Entity` on enum violations, range violations, type mismatches. FastAPI standard shape:

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

Field path in `loc[]`. Use Dart enums + `.name` when sending — eliminates the entire class of these errors.

---

## 7. What you can delete from your existing code

Once you're on the new endpoints:
- The `submitOnboarding` POST call from the chat finish step — not needed; PATCH already saved everything.
- `FinishedFooter` "Save changes" button — not needed; auto-saved.
- `OnboardingStateStore` as the in-progress source of truth — demoted to retry queue only.
- Bootstrap "saved local snapshot vs backend prefill" priority logic — server is truth, local fills the gap during the session only.

---

## 8. Confirmed answers to your three open questions

- ✅ **Path**: `PATCH /v1/patients/profile`
- ✅ **Response shape**: full reconciled profile (section 3). Push into `ProfileViewModel.profileResponse`.
- ✅ **Old POST `/v1/patients/onboarding`**: stays alive but optional. Stop calling it; we'll delete server-side in a later cleanup PR when no client uses it.

Go.
