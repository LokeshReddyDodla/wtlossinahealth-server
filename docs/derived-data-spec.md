# Derived-Data Engine — dirty-set + per-patient drain

Status: SPEC — approved direction, not yet implemented.
Owner: platform. Supersedes: per-modality trigger fan-outs, all report/panel
reconcile crons, month-granular freshness filters.

## 1. Problem

All derived artifacts (reports, vectors, panel, summary) are wired ad-hoc at
each producer callsite. Measured consequences (Aug 2026 pipeline + panel
studies):

- **O(producers × consumers) wiring, with misses.** Panel is updated only on
  patient creation (`lib/services/patient_profile_service.py:379`); HealthKit
  SMBG is never vectorized (`lib/services/fitness_upload_service.py:212-233`);
  summary staleness is a commented-out no-op
  (`lib/utils/patient_summary_stale.py`).
- **Redundant recompute.** N meals logged = N full daily-report regens
  (second-resolution job ids defeat dedup,
  `lib/workers/tasks/meal/report_generation.py:62`); one fitness sync
  regenerates whole *months* of sleep+fitness reports (month-granular
  freshness filter); LLU polls every 5 min with no coalescing primitive.
- **Sweeps scale with roster, not with change.** Panel full-roster reconcile
  starved the Postgres pool (4551 queued jobs; disabled in `f6e75867`); the
  CGM 30-min reconcile walks frontiers regardless of activity.
- **Cross-queue races.** Report and vector jobs land on different queues with
  no ordering (the `e6883b8f` Qdrant-drift bug class); panel wired naively to
  uploads would race report generation.
- **Fire-and-forget enqueues have no durability floor** — every reconciler
  cron exists to compensate for lost triggers.

## 2. Decision

One primitive: **the unit of change is `(patient_id, domain, date)`** — a
*dirty cell*. Producers mark cells dirty; a single per-patient drain job
recomputes exactly the dirty days, in dependency order, then runs cross-domain
finalizers, then clears the cells it claimed.

Load becomes proportional to data change (idle patients cost zero — no crons
anywhere). Coalescing is structural (set semantics). Ordering is structural
(one job per patient: reports → vectors → finalizers). Durability is
structural (cells clear only on success).

### Alternatives rejected

- **Pure pub/sub events**: fixes wiring but not redundancy; coalescing and
  ordering stay hand-rolled per subscriber; ephemeral (lost enqueue = lost
  change, keeps reconcilers mandatory).
- **Temporal**: durable execution for free, but requires operating a Temporal
  cluster to replace ~200 lines; our flows are 3 linear hops, not sagas.
- **Dagster/Prefect**: declarative assets + staleness is the right concept,
  wrong latency/ops model (batch data-eng daemons).
- **Kafka/CDC**: solves throughput we don't have; problem is redundancy.
- **Celery/taskiq**: lateral queue move, no dirty tracking.

### Off-the-shelf we DO adopt

**PgBouncer** (transaction pooling) in front of Postgres. Root cause of the
pool incident is `pool_size=100` per process × 7 processes vs
`max_connections=100` (`lib/core/postgres_store.py:20-29`,
`deployment/rest_server/Dockerfile:48`, 5 arq containers). PgBouncer fixes
the arithmetic permanently instead of retuning `pool_size` per process count.

## 3. Dirty-cell contract

Mongo collection `derived_dirty_cells` (replica set rs0 → atomic ops OK):

```
{
  patient_id: str,
  domain:     str,        # DataDomain enum value
  date:       "YYYY-MM-DD",  # patient-local day that changed
  marked_at:  datetime,   # bumped on every re-mark
}
unique index: (patient_id, domain, date)
index: (patient_id)
```

- `mark_dirty(patient_id, domain, dates)` = bulk upsert (`$set marked_at`,
  `$setOnInsert` rest) + `enqueue_job("refresh_patient", patient_id,
  _job_id=f"derived:refresh:{patient_id}", _defer_by=<domain defer>)`.
  Duplicate enqueue returns None — that's the coalescing working.
- Domain enum: reuse/align with the existing `DomainName` enum
  (per no-hardcoded-lists rule); values: `cgm, meal, sleep, fitness, smbg,
  vitals, workout`.
- Mark failures are logged, never raised into the write path (same policy as
  `enqueue_panel_recompute`, `lib/workers/tasks/patient_panel/recompute.py:49`).

### Defer windows (registry-configured per domain)

| domain | `_defer_by` | rationale |
|---|---|---|
| all user-action uploads (meal, smbg, vitals, workout, fitness, sleep, CGM file uploads) | **0 — immediate** | users refresh right after syncing; the burst arrives inside one request anyway, and single-flight + durable cells coalesce overlapping work |
| cgm live stream (LLU) | 900 s | bound regen frequency for streamers; rides a **separate job id** (`derived:refresh:{pid}:deferred`) so a pending slow kick can never delay a user-action's immediate one |

Defer is a coalescing hint, never a correctness dependency. Mid-drain marks
re-kick at 30 s.

## 4. The drain: `refresh_patient(patient_id)`

Queue `Queues.REPORTS`, `keep_result=0`, stable job id, `max_tries=2`.

1. **Claim**: `claim_ts = now`; read all cells for patient.
   Empty set → engagement-only path (recompute finalizers, e.g. panel
   time-based rules) → done. (This is the provider-side refresh, §6.)
2. **Compute, DAG order per domain** (registry order): for each dirty date,
   `domain.compute_daily(patient_id, date)`; then
   `domain.rollup(affected weeks/months)` — only periods containing dirty
   days. This replaces the month-granular freshness filters
   (`lib/workers/tasks/sleep/report_generation.py:16-90`,
   `fitness/report_generation.py:17-101`).
3. **Vectors**: collect changed report ids across domains; enqueue ONE vector
   job per patient on `Queues.VECTORS` carrying the ids. Vector job re-reads
   Mongo (the `e6883b8f` invariant: only ids cross the queue boundary).
4. **Finalizers**, once, after all domains: registered cross-domain
   read-models. v1: panel recompute (inline call, not a separate job — the
   drain already holds the patient context). Later: summary staleness, any
   future consumer.
5. **Clear**: delete claimed cells with filter
   `{_id ∈ claimed, marked_at: {$lte: claim_ts}}` — a cell re-marked during
   the run survives.
6. **Self-re-enqueue**: if the dirty set for this patient is non-empty after
   clearing, re-enqueue self (`_defer_by=60`). REQUIRED — arq drops a
   duplicate `_job_id` while the job is *running*, so marks landing mid-drain
   would otherwise wait for the next unrelated activity.
7. **Failure**: task re-raises (arq retry). Cells stay dirty on final failure;
   next mark or provider-refresh retries. `task_runs` doc records the failure
   (`lib/workers/tasks/base.py:43`).

## 5. Interfaces

```python
class ReportDomain(Protocol):
    domain: DataDomain
    defer_s: int
    async def compute_daily(self, patient_id: str, date: date) -> list[ChangedReport]
    async def rollup(self, patient_id: str, periods: list[Period]) -> list[ChangedReport]
    # vectorize stays on the existing per-modality vector services;
    # the drain only forwards changed report ids.

class Finalizer(Protocol):
    async def run(self, patient_id: str, changed: DrainSummary) -> None
```

Registration: one module, `lib/derived/registry.py` — dict, not a plugin
system. Adding a domain or consumer = one entry.

The `ReportDomain` implementations are where the **report base class**
refactor lands: shared `_generate_report_id` (sha256 scheme, today duplicated
4×), shared `save_report/save_reports_bulk` (`ReplaceOne` upsert — fixes
sleep's `UpdateOne+$set` stale-field bug, `lib/services/reports/sleep/service.py:265`),
shared `ReportMetadata`/`DateRange` schema (today defined 4×), and Mongo
indexes on all four report collections
(`patient_id + metadata.report_type + metadata.date_range.start`) — today
there are none.

## 6. Provider-side stale refresh (lapsed detection without crons)

LAPSED/DATA_GAP transitions fire when a patient *stops* uploading — the one
moment no upload event exists. Trigger from the other user:
`GET /dashboard/metrics/patients/panel` fire-and-forgets
`refresh_patient` for returned rows with `computed_at` older than
`PANEL_STALE_REFRESH_HOURS` (default 6). Dedup makes this free to spam; the
list still returns instantly from Mongo; rows refresh in background. Same
pattern as the patient-brief regenerate-on-read cooldown.

## 7. Producer choke points (mark_dirty callsites)

| producer | today | marks |
|---|---|---|
| Meal save/update/delete | `trigger_meal_tasks` fan-out (`lib/services/meal/helpers.py:108`; delete at `service.py:626`) | `meal` for meal date(s) — old AND new date on date-changing edits |
| CGM CSV/file uploads | 3 paths in `lib/services/cgm_upload_service.py:67,194,248` | `cgm` for reading dates; also `meal` for the refresh window (replaces `_enqueue_meal_report_refresh:431`) |
| CGM live (LLU) | nothing (reconcile cron compensates) | `cgm` for reading dates, 900 s defer — **deletes the reconcile cron** |
| Fitness upload | manual fan-out (`lib/services/fitness_upload_service.py:34-107`) | `fitness`, `sleep`, `vitals`, `smbg` for sample dates — fixes HealthKit-SMBG invisibility as a side effect |
| SMBG manual save/update/delete | inline vector calls (`lib/services/patient_smbg_service.py`) | `smbg` |
| Vitals upload | inline vector enqueue (`lib/services/patient_vital_service.py:117`) | `vitals` |
| Workout CRUD | 3 `_fire_*` hooks (`lib/services/patient_workout_service.py:436-483`) | `workout` (panel/fitness-report input) |
| Sleep check-in | direct report enqueue (`lib/services/daily_checkin_service.py:118-131`) | `sleep` |
| Admin ops | per-feature endpoints | every "fix" button = `mark_dirty(cohort, domain, range)` — the Admin Ops panel becomes one endpoint |

## 8. What gets deleted when migration completes

- Panel reconcile cron machinery + dormant `reconcile_patient_panel`
  (`lib/workers/tasks/patient_panel/`)
- CGM `cgm-reconcile-vectors` cron (`lib/workers/tasks/cgm/__init__.py:29-40`,
  `reconcile.py`)
- `trigger_meal_tasks` + per-callsite job-id bucketing hacks
- Sleep/fitness month-freshness filters
- `ArqTaskManager` report wrappers (already dead/broken,
  `lib/managers/arq_task_manager.py:26`)
- `POST /v1/reports/meal/sync`'s bespoke date logic (folds into mark_dirty;
  also fixes its uploaded_at-vs-report-date bug)

Keep: lazy generate-on-404 in report reads (harmless backstop), day-view
resolve-at-read (it reads materialized reports).

## 9. Consistency model (stated plainly)

- Mark-dirty sits in the write path *after* the data write; if the mark
  itself fails, the trigger is lost until the next activity, a provider
  panel view, or an admin mark. No outbox table until evidence demands one.
- Reports and vectors can diverge for the seconds between drain step 2 and
  the vector job — same as today, but now bounded and ordered per patient.
- `_safe`-style per-source degradation inside panel recompute must NOT
  delete rows or flip assessments on transient failure (fix
  `lib/services/patient_panel/service.py:114-116` as part of finalizer
  migration: skip upsert when a required source errored).

## 10. Prerequisites (slice 0 — ship before any new fan-out)

1. PgBouncer container + drop app `pool_size` to ~10/process
   (`lib/core/postgres_store.py:22`).
2. Collapse `panel_context`'s 7 sequential queries / single held session
   (`lib/services/patient_panel/context.py:108-207`) — frontier loop is one
   UNION, DH/RH are joins.
3. Bound the SMBG fallback read (window + limit,
   `lib/services/patient_smbg_service.py:41-44`) and recency-bound
   `get_latest_vitals` for panel inputs.

## 11. Migration slices (each ships alone; old triggers live until deleted)

| slice | contents | deletes |
|---|---|---|
| 0 | prerequisites above | — |
| 1 | `derived_dirty_cells` + `mark_dirty` + `refresh_patient` skeleton (claim/clear/self-re-enqueue, no domains yet) + panel as finalizer #1 + mark_dirty lines at all §7 choke points + provider stale-refresh on GET /panel | panel reconcile machinery |
| 2 | Meal implements `ReportDomain` (report+rollup into drain; vector ids forwarded) — proves the interface | `trigger_meal_tasks`, meal job-id hacks, meal-sync bespoke logic |
| 3 | CGM domain (daily/weekly/custom into drain; LLU marks dirty) | CGM reconcile cron |
| 4 | Sleep + fitness domains; report base class lands here (shared id/save/metadata/indexes) | month freshness filters, sleep `$set` save |
| 5 | SMBG + vitals thin daily rollup docs join the drain (kills SMBG compute-per-request; starts retiring 8+ hand-rolled vitals SQL sites) | — |
| 6 | Summary as finalizer #2 (resurrects the dead staleness chain); Admin Ops = mark-dirty endpoint | `mark_summary_stale_and_enqueue` corpse |

## 12. Scale envelope

10k patients, ~30% daily active, ~3 syncs/day → ~9k drain jobs/day, each
bounded to dirty days, coalesced per burst; panel recompute ∝ activity;
reads fully materialized. Same design holds at 100k patients by adding
worker replicas — nothing structural changes. Ceiling remains Postgres,
which is what slice 0 addresses.
