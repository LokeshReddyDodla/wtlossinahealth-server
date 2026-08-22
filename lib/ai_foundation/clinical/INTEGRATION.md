# aihealth_brain — shadow land

The live meal-preview glucose number the patient sees is still produced
by `GlucosePredictor` (LLM) when the June `MetabolicService` path does
not emit a showable number. This land does **not** flip that.

`from aihealth_brain import assess` is the importable one-file API.
The wrapper at `lib/ai_foundation/clinical/aihealth_brain.py` has no
clinical coefficients. It calls the June `MetabolicEngine.assess` until
the pin-copy is dropped in.

## Flag (off by default)

| Knob | Default | Effect |
|---|---|---|
| `BRAIN_SHADOW_ENABLED` or `AI_BRAIN_SHADOW_ENABLED` | `false` | When true, meal preview also calls `assess()` and writes a `brain_shadow` log row. The returned `GlucosePrediction` is unchanged. |

Do not enable in production as a serving flip. Shadow only.

## Drop the pin-copy (Mukthar)

1. Take the Mac pin `aihealth_brain.py` v2.2.0 (stdlib, F070 inlined).
2. Save it as **`aihealth_brain_pin.py`** next to the wrapper
   (`lib/ai_foundation/clinical/aihealth_brain_pin.py`) or at repo root.
3. Do **not** overwrite `aihealth_brain.py` (root shim) or the wrapper —
   those apply: fail-closed on `safety_floor`, `events` →
   `recent_cgm_events`, and strip `lever`/`levers` on SAFETY (no
   `protein_first` leak).
4. Restart the process. `assess()` will load the pin on first call.
5. Set `BRAIN_SHADOW_ENABLED=true` in a non-prod env to compare logs
   against the LLM / MetabolicService serving path.

## What this PR does not do

- Does not change patient-facing LLM prose or the glucose prompt.
- Does not edit `lib/ai_foundation/clinical/metabolic/data/levers.json`.
- Does not delete the June metabolic port or `GlucosePredictor`.
- Does not make `assess()` the serving response.

Lokesh reviews only if the patient-visible LLM contract changes.
This land keeps that contract as-is.
