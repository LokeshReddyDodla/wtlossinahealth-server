-- ───────────────────────────────────────────────────────────────────────────
-- Onboarding soak verification
-- Run these during the verification window (Deploy 1 → Deploy 2).
-- Every query should return 0 rows (or only rows you've consciously accepted).
-- ───────────────────────────────────────────────────────────────────────────

-- 1. patients.timezone parity with locale
-- Expected: 0 — every patient should have timezone populated to match locale.
SELECT COUNT(*) AS missing_timezone
FROM patients
WHERE timezone IS NULL AND locale IS NOT NULL;

SELECT patient_id, locale, timezone
FROM patients
WHERE timezone IS DISTINCT FROM locale
LIMIT 20;

-- 2. smoking_habit.status parity with smoke_status bool
-- Expected: 0 — status='CURRENT' iff smoke_status=TRUE (for new rows written via dual-write).
-- Old backfilled rows may have status=FORMER while smoke_status=FALSE; that's OK.
SELECT COUNT(*) AS status_bool_mismatch
FROM patient_smoking_habit
WHERE status IS NOT NULL
  AND (
    (status = 'CURRENT' AND smoke_status <> TRUE) OR
    (status = 'NEVER'   AND smoke_status <> FALSE)
  );

-- 3. alcohol_consumption.status parity with consume_alcohol bool
-- Expected: 0 — status='NEVER' iff consume_alcohol=FALSE (new rows).
SELECT COUNT(*) AS alcohol_status_mismatch
FROM patient_alcohol_consumption
WHERE status IS NOT NULL
  AND (
    (status = 'NEVER' AND consume_alcohol <> FALSE) OR
    (status <> 'NEVER' AND consume_alcohol <> TRUE)
  );

-- 4. drinks_per_session parity with legacy quantity string
-- Expected: 0 — quantity should be the stringified drinks_per_session for new rows.
SELECT COUNT(*) AS drinks_string_mismatch
FROM patient_alcohol_consumption
WHERE drinks_per_session IS NOT NULL
  AND quantity IS DISTINCT FROM drinks_per_session::text;

-- 5. sleep_habit.average_sleep_hours parity with legacy string
-- Expected: 0 for new rows. Old rows where average_sleep_duration was "8 hours" stay legacy-only.
SELECT COUNT(*) AS sleep_hours_string_mismatch
FROM patient_sleep_habit
WHERE average_sleep_hours IS NOT NULL
  AND average_sleep_duration IS DISTINCT FROM average_sleep_hours::text;

-- 6. Rows where backfill couldn't recover (legacy data present but new column NULL)
-- These are the rows you may need to ask patients to re-fill, or accept as legacy noise.
SELECT 'smoking' AS table_name, COUNT(*) AS unbackfilled
FROM patient_smoking_habit WHERE smoke_status IS NOT NULL AND status IS NULL
UNION ALL
SELECT 'alcohol', COUNT(*)
FROM patient_alcohol_consumption WHERE consume_alcohol IS NOT NULL AND status IS NULL
UNION ALL
SELECT 'sleep_hours', COUNT(*)
FROM patient_sleep_habit
  WHERE average_sleep_duration IS NOT NULL AND average_sleep_hours IS NULL
UNION ALL
SELECT 'drinks', COUNT(*)
FROM patient_alcohol_consumption
  WHERE quantity IS NOT NULL AND drinks_per_session IS NULL;

-- 7. Sanity: count of patients onboarded via the new endpoint
-- Should be > 0 once the new endpoint is live.
SELECT
  COUNT(*) AS new_onboarded
FROM patients p
WHERE p.timezone IS NOT NULL
  AND (p.profile_completion ->> 'basic') LIKE '%true%';
