# Patient Panel Signal — design spec

The read model behind the enriched **Patients** roster (Triage + Data grid lenses)
and the future **Panel** triage view. One precomputed row per patient; both
surfaces read it. Zero per-patient AI at read time.

Status: proposed · Author: — · Depends on: cgm reports, day_view, progress,
vitals, patient briefs, EventBus.

---

## 1. Goal & principles

A care provider with 500+ patients must open the roster and, in one server-side
query, sort/filter/scan a page of patients by any clinical signal — **without**
computing 500 CGM reports or 500 AI briefs on the request.

Principles:
- **One materialized read model.** Both lenses read the same `patient_panel_signal`
  row. No cross-collection joins on the request path.
- **Deterministic signals, no read-time AI.** Status and the "what needs attention"
  reason are computed by auditable clinical rules. The AI brief stays the cached
  per-patient drill-down (and, optionally, a single cohort summary).
- **Modality-agnostic.** Every field is nullable; a patient with SMBG, labs,
  weight-only, or nothing is a first-class row (CGM fields just resolve to null).
- **Facility/CP scoped.** A provider sees only their patients — reuse the existing
  tenancy path, never a new one.

---

## 2. Architecture decision — materialized read model (CQRS)

**Decision: a denormalized `patient_panel_signal` collection, one row per patient,
updated event-driven, read directly.**

Why not query-time aggregation (what `dashboard_metrics` does today)?
- Today's cross-patient endpoints (`rest_server/dashboard_metrics/read.py` →
  `CGMMetricsService._find_patients_with_events`,
  `lib/services/dashboard_metrics/cgm_metrics_service.py:81`) query
  `cgm_report_collection` with a **single-metric** filter (e.g. hyper events) +
  projection + skip/limit. That works for one filter.
- The Data grid needs **arbitrary multi-column sort/filter** (sort by CV, filter
  TIR<70 AND adherence<50%, across CGM + labs + adherence + brief). Doing that at
  query time means joining `cgm_report_collection` + progress + vitals +
  `patient_briefs` per page — heavy, and impossible to index for every sort key.
- A materialized row makes **every column a cheap indexed sort/filter**, and
  decouples read latency (O(page)) from compute (event-driven, per patient).

This is the same pattern already in the codebase: the brief cache
(`lib/services/patient_brief/service.py`, one row per patient, refreshed on
cadence) and the CGM vector reconciler (event/sweep materialization). We extend
it, we don't invent a pattern.

Trade-off accepted: **eventual consistency.** A signal row lags its source by the
materialization delay (seconds via events, bounded by the sweep). Acceptable — a
triage roster is not a real-time monitor.

---

## 3. Data sources — every field maps to real code

| Signal | Source | Where |
|---|---|---|
| CGM: TIR, avg, CV, GMI, %<70, %<54, %>180, %>250, nocturnal<70, hyper/hypo events, TIR/avg **delta** | latest daily/custom CGM report | `cgm_report_collection` (Mongo); shape in `lib/schemas/cgm_stats.py` (`CGMRangeStats`, `CGMSummaryStats`, `CGMTrend`) |
| A1c, FBS, BP, weight | vitals/labs | `lib/services/patient_vital_service.py`, resolved in `lib/services/day_view/repository.py` |
| Adherence (doses/tasks) | care plan progress | `lib/services/progress/resolver.py` + `medication_service`, `patient_diet_plan_service`, `patient_fitness_plan_service`, `checkin_history_service` |
| Clinical alerts (TIR-band breach, hyper/hypo, missed dose) | deterministic day-view alerts | `lib/services/day_view/repository.py` (already computes them per day) |
| Last glucose + source + sync status | reading frontier + connected app | `PatientLibreView/Sinocare.last_cgm_reading_at`; SMBG timestamps; sync-stale = connected but frontier older than N days (the reconciler signal) |
| Last active (app engagement) | patient activity | patient profile / activity log — **distinct** from last glucose |
| Conditions, modality, demographics | patient profile | Postgres patient model |
| assessment + verdict (optional enrichment) | cached AI brief | `patient_briefs` collection (`lib/services/patient_brief/service.py`) |
| Tenancy (facility_id, care_provider_id) | patient ↔ CP mapping | `lib/utils/patient_mapping.py` (`map_patients_to_reports`), `resolve_patient_scope` |

All CGM metrics are already **bulk-readable** from `cgm_report_collection` (that's
what `_find_patients_with_events` does) — so materialization reads are cheap.

---

## 4. Signal row schema (typed contract)

`lib/schemas/patient_panel_signal.py` (new). Pydantic; every clinical field
nullable (modality-agnostic).

```
class PanelAssessment(str, Enum): RESPONDING, WATCH, AT_RISK, DATA_GAP, NOT_STARTED
class GlucoseSource(str, Enum): CGM, SMBG, LABS, NONE
class Modality(str, Enum): CGM, SMBG, LABS, WEIGHT, NONE

class PatientPanelSignal(BaseModel):
    patient_id: str
    facility_id: str | None
    care_provider_ids: list[str]          # tenancy filter
    # identity
    name; age; sex; conditions: list[str]; modality: Modality
    # triage (deterministic)
    assessment: PanelAssessment
    reason: str                           # templated one-liner; the "what needs attention"
    reason_severity: Literal["urgent","watch","info"]
    priority: int                         # sort key: derived from assessment + severity
    # glucose (nullable)
    tir_pct; tir_delta; avg_glucose; cv_pct; gmi; below_70_pct; below_54_pct
    above_180_pct; above_250_pct; nocturnal_below_70_pct; hypo_events; hyper_events
    # other modalities
    a1c; fasting_glucose; smbg_avg; weight_delta_kg
    # engagement
    last_glucose_at; last_glucose_source: GlucoseSource; glucose_sync_stale: bool
    last_active_at; adherence_pct; doses_done; doses_total; tasks_done; tasks_total
    alert_count; alert_worst: Literal["urgent","watch"] | None
    # provenance
    computed_at: datetime
    sources_fresh_as_of: dict[str, datetime]   # per-source freshness (auditability)
```

Frontend camel mirror in `types.ts`.

---

## 5. Deterministic status + reason (NO AI)

Pure rules over the fields above — auditable, cheap, works for every patient.
Evaluated top-down; first match wins (severity order):

- **not_started** — never any reading/log and enrolled < profile threshold.
- **data_gap** — no glucose (CGM or SMBG) in N days, OR < K readings in the
  window, OR `glucose_sync_stale` (connected but frontier stale). Reason names the
  gap ("CGM not syncing · 8d", "Only 3 readings / 2wk", "Logging stopped ~1mo").
- **at_risk** — severe/nocturnal hypo over threshold, frequent lows, A1c ≥ 9,
  TIR < 50, or a rising-average trend past threshold. Reason names the driver
  ("Nocturnal hypo 41% · GMI 6.0→7.0").
- **watch** — TIR 50–70, fasting above goal, sharp activity/adherence drop, or a
  mild adverse trend.
- **responding** — none of the above; on-target or improving.

`reason` is a **template**, not prose: `"{driver} · {supporting}"` filled from the
matched rule's fields. Deterministic, testable, no LLM. Thresholds live in one
config module (condition-aware: pregnancy/GDM TIR targets differ — reuse the
consensus tiers already added for the day-view clinical alerts).

> The cached brief's `verdict` MAY override `reason` for patients who have a fresh
> brief (richer wording), but the rule-based reason is the guaranteed default so
> all 500 render without any AI.

---

## 6. Materialization — event-driven + sweep

`lib/services/patient_panel/service.py` (new) + a worker.

Recompute a patient's row (idempotent upsert, keyed on `patient_id`) when its
inputs change. Subscribe on the EventBus (`lib/ai_foundation/events/schemas.py`
`HealthEventType`) and hook the existing workers:

- CGM report regenerated (report-gen / reconciler worker just built) → recompute.
- `GLUCOSE_READING`, `VITAL_RECORDED`, `PATIENT_DISENGAGED`, adherence/care-plan
  change, brief updated → recompute (debounced per patient).
- **Reconciliation sweep** (cron, reusing the CGM reconciler pattern) — recompute
  rows whose `computed_at` is older than the source's newest change; catches any
  missed event. Belt-and-suspenders, same as the vector reconciler.

Compute reads are bulk-friendly (CGM from Mongo, adherence from progress, vitals
from vital service) — a single patient's row is a handful of indexed reads.

Cost: recompute is per-patient-on-change, not per-page-on-read. A patient with
frequent live CGM coalesces (debounce), same principle as the brief cadence.

---

## 7. Multi-tenancy — reuse, don't reinvent

Every read is scoped to the caller's patients. Reuse `resolve_patient_scope`
(`rest_server/dashboard_metrics/read.py`) → `(health_facility_id,
care_provider_id, is_facility_admin)` and store `facility_id` +
`care_provider_ids` on the row so the read is a single indexed filter — no
per-request join to resolve visibility.

---

## 8. Read API

`GET /v1/care-providers/patients/panel`

Query: `lens=triage|grid`, `status`, `modality`, `condition`, `search`,
`sort` (any signal field), `order`, `page`, `size`, `columns` (grid).

Handler: `resolve_patient_scope` → single indexed `find` on
`patient_panel_signal` with the scope + filters + sort + skip/limit → typed page.
One query, no AI, no fan-out. Provider-gated exactly like `/day` and `/brief`.

Optional: `GET …/panel/summary` → the **single** cohort AI call (one brief over
the panel counts) for the Panel view's header band. One call for the whole panel,
never per patient.

---

## 9. Indexes

`patient_panel_signal`:
- `{facility_id:1, care_provider_ids:1, priority:1}` — default triage sort.
- `{facility_id:1, assessment:1}` — status filter.
- `{facility_id:1, modality:1}` — modality filter.
- Per hot sort key (tir_pct, cv_pct, gmi, adherence_pct, last_glucose_at) as
  compound with facility_id, added as real sort usage shows (don't pre-index all).
- Unique on `patient_id`.

Created at startup via `ensure_indexes()`, wired in `app/main.py` like the other
Mongo services (the pattern the brief index already uses).

---

## 10. What's reused vs new

Reused: `cgm_report_collection` + `CGMMetricsService` query style; `day_view`
alert computation; `progress` adherence; `patient_vital_service`; `patient_briefs`
cache; `patient_mapping`/`resolve_patient_scope`; EventBus; the reconciler sweep
pattern; the brief's startup-index convention.

New: `patient_panel_signal` collection + `PatientPanelSignal` schema; the
deterministic status/reason rule module (+ thresholds config); the panel service
(compute + upsert); the materialization worker/subscriptions; the read endpoint;
frontend types + the table wiring.

---

## 11. Build order (phased, each shippable)

1. **Schema + rules + compute-one** — `PatientPanelSignal`, the rule module (with
   a unit test suite over the rules — deterministic, so fully testable), and
   `compute_signal(patient_id)`. No storage yet.
2. **Materialize + sweep** — collection, upsert, event subscriptions, the sweep
   cron, startup index.
3. **Read API** — the scoped paginated endpoint.
4. **Frontend** — enriched Patients table (Triage + Grid) on the endpoint;
   column editor; filters/sort.
5. **Panel view** — the curated cohort feed + the single cohort-summary AI call.

---

## 12. Risks / open questions

- **Reason quality without AI** — templates must read naturally across conditions;
  the rule suite + a few real-data spot checks guard this. (This is why the rules,
  not prose, are the default.)
- **Freshness expectations** — define the sweep interval so "last glucose 20m ago"
  is trustworthy; store per-source freshness (`sources_fresh_as_of`) for honesty.
- **Threshold ownership** — the clinical thresholds are a medical decision; put
  them in one reviewed config, condition-aware, reusing the day-view consensus
  tiers.
- **Backfill** — first rollout computes rows for the whole panel once (a batch job,
  bounded/scoped), same shape as the CGM vector backfill.
