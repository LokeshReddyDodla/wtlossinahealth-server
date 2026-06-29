"""
Outcome loop — append-only advice ledger that tracks whether nudges actually work.

ADVISE -> LOG (write the event BEFORE delivery; this is what makes it testable)
       -> FOLLOW-UP (next same-trigger instance: did the patient COMPLY, did the outcome move as predicted)
       -> ROLL UP (per trigger: compliance rate, predicted vs observed delta, efficacy).

Track-agnostic: works for "glucose" (outcome = spike change, mg/dL) and "obesity" (outcome = weight/
body-composition change, %). Pure stdlib, append-only JSONL ledger. No live data needed to run the mechanism;
wire FOLLOW-UP to live CGM / InBody once the read-only service token is provisioned.
"""
import json, os, time, uuid, tempfile

# ---------------------------------------------------------------- ledger I/O
def log_advice(ledger_path, event):
    """Write an advice event BEFORE delivery. Returns the event_id."""
    event = dict(event)
    event.setdefault("event_id", uuid.uuid4().hex[:12])
    event.setdefault("logged_ts", time.time())
    # follow-up fields start empty — filled at the next same-trigger instance
    for k in ("complied", "compliance_evidence", "compliance_ts", "observed_delta", "outcome_vs_predicted"):
        event.setdefault(k, None)
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    return event["event_id"]

def record_followup(ledger_path, event_id, complied, observed_delta=None, evidence=None):
    """Fill the follow-up on a logged event (rewrites the ledger; fine at advice-ledger scale)."""
    rows = _read(ledger_path)
    for r in rows:
        if r.get("event_id") == event_id:
            r["complied"] = bool(complied)
            r["compliance_evidence"] = evidence
            r["compliance_ts"] = time.time()
            r["observed_delta"] = observed_delta
            pd = r.get("predicted_delta")
            if complied and observed_delta is not None and pd is not None:
                # did it move in the predicted direction? (predicted_delta < 0 means "should drop")
                r["outcome_vs_predicted"] = "as_predicted" if (observed_delta <= 0) == (pd <= 0) else "opposite"
    _write(ledger_path, rows)

def _read(p):
    if not os.path.exists(p): return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

def _write(p, rows):
    with open(p, "w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r) + "\n")

# ---------------------------------------------------------------- engine -> event
def advice_event_from_contract(contract, patient_token, track, trigger, ts=None):
    """Map an EngineV2 contract into a ledger advice event. Returns None for non-actionable contracts:
    ONLY a cited SUGGEST is logged as efficacy-predicting advice (Forge P1). REINFORCE / STATE_FACTS /
    FLAG / SAFETY are never logged here. Token-keyed, never a name or id."""
    if track == "glucose":
        if contract.get("output_mode") != "SUGGEST":
            return None
        lever = contract.get("lever") or {}
        cite = lever.get("cite")
        if not cite:                                          # a SUGGEST without a citation is not advice
            return None
        predicted_delta = lever.get("effect_mgdl")           # expected mg/dL change (negative = drop)
        move = lever.get("say")
    else:  # obesity
        b = contract.get("bmiq") or {}
        if b.get("output_mode") != "SUGGEST":
            return None
        lv = b.get("lever") or {}
        cite = lv.get("cite")
        if not cite:
            return None
        predicted_delta = lv.get("effect_pct")               # may be absent -> marked unknown below
        move = lv.get("name") or lv.get("priority")
    return {
        "patient_token": patient_token, "track": track, "trigger": trigger,
        "ts": ts or time.time(),
        "output_mode": "SUGGEST",
        "move": move,
        "predicted_delta": predicted_delta,
        "predicted_delta_known": predicted_delta is not None,   # explicit unknown marker (BMIQ levers carry no effect)
        "cite": cite,
        "confidence": (contract.get("prediction") or {}).get("confidence"),
    }

# ---------------------------------------------------------------- rollup
def rollup(ledger_path, valid_floor=10):
    rows = _read(ledger_path)
    groups = {}
    for r in rows:
        key = (r.get("track"), r.get("trigger"))
        groups.setdefault(key, []).append(r)
    out = []
    for (track, trig), evs in sorted(groups.items()):
        n = len(evs)
        followed = [e for e in evs if e.get("complied") is not None]
        complied = [e for e in followed if e.get("complied")]
        with_outcome = [e for e in complied if e.get("observed_delta") is not None and e.get("predicted_delta") is not None]
        comp_rate = (len(complied) / len(followed)) if followed else None
        mean_pred = (sum(e["predicted_delta"] for e in with_outcome) / len(with_outcome)) if with_outcome else None
        mean_obs = (sum(e["observed_delta"] for e in with_outcome) / len(with_outcome)) if with_outcome else None
        as_pred = sum(1 for e in with_outcome if e.get("outcome_vs_predicted") == "as_predicted")
        out.append({
            "track": track, "trigger": trig, "advices": n,
            "compliance_rate": (round(comp_rate, 2) if comp_rate is not None else None),
            "n_with_outcome": len(with_outcome),
            "mean_predicted_delta": (round(mean_pred, 1) if mean_pred is not None else None),
            "mean_observed_delta": (round(mean_obs, 1) if mean_obs is not None else None),
            "moved_as_predicted_pct": (round(100 * as_pred / len(with_outcome)) if with_outcome else None),
            "valid": len(with_outcome) >= valid_floor,   # single events are noise; only call efficacy above a floor
        })
    return out

# ---------------------------------------------------------------- self-test (mechanism, synthetic)
def demo():
    led = os.path.join(tempfile.gettempdir(), "advice_ledger_demo.jsonl")
    if os.path.exists(led): os.remove(led)
    # contract-mapper guard (Forge P1): only a cited SUGGEST is logged; everything else is not advice.
    assert advice_event_from_contract({"output_mode": "REINFORCE"}, "tok", "glucose", "t") is None
    assert advice_event_from_contract({"output_mode": "STATE_FACTS"}, "tok", "glucose", "t") is None
    assert advice_event_from_contract({"output_mode": "SUGGEST", "lever": {"say": "x", "effect_mgdl": -7.5}}, "tok", "glucose", "t") is None
    _ev = advice_event_from_contract({"output_mode": "SUGGEST", "lever": {"say": "x", "effect_mgdl": -7.5, "cite": "q1"}, "prediction": {"confidence": "moderate"}}, "tok", "glucose", "t")
    assert _ev and _ev["patient_token"] == "tok" and _ev["cite"] == "q1" and _ev["predicted_delta_known"], _ev
    assert advice_event_from_contract({"bmiq": {"output_mode": "REINFORCE"}}, "tok", "obesity", "t") is None
    # GLUCOSE: advise protein-first on high-carb breakfasts; predicted -7.5 mg/dL (q1)
    ids = []
    for i in range(12):
        ev = {"patient_id": "p%02d" % i, "track": "glucose", "trigger": "high_carb_breakfast",
              "output_mode": "SUGGEST", "move": "veg/protein first, carbs last",
              "predicted_delta": -7.5, "confidence": "moderate"}
        ids.append(log_advice(led, ev))
    # follow-up: 9 complied; of those, 7 spikes dropped (~ -8), 2 went up (+3); 3 did not comply
    import random; random.seed(1)
    for k, eid in enumerate(ids):
        if k < 9:
            obs = -8.0 if k < 7 else 3.0
            record_followup(led, eid, True, observed_delta=obs, evidence="next breakfast carb cut >10g")
        else:
            record_followup(led, eid, False, evidence="no carb change")
    # OBESITY: advise protein+resistance on rapid-lean-loss GLP-1 users; predicted -X% lean loss
    for i in range(11):
        eid = log_advice(led, {"patient_id": "o%02d" % i, "track": "obesity", "trigger": "glp1_rapid_lean_loss",
                               "output_mode": "FLAG", "move": "protein 1.2-1.6 g/kg + 2x/wk resistance",
                               "predicted_delta": -2.0, "confidence": "moderate"})
        record_followup(led, eid, i % 4 != 0, observed_delta=(-1.5 if i % 4 != 0 else 0.5),
                        evidence="InBody SMM delta next scan")
    rep = rollup(led, valid_floor=8)
    print("=== ADVICE-LEDGER ROLLUP (synthetic mechanism check) ===")
    for r in rep:
        print(" ", json.dumps(r))
    # assertions on the mechanism
    g = next(r for r in rep if r["trigger"] == "high_carb_breakfast")
    assert g["advices"] == 12 and g["compliance_rate"] == 0.75, g
    assert g["n_with_outcome"] == 9 and g["moved_as_predicted_pct"] == 78, g  # 7/9
    assert g["valid"] is True, g
    o = next(r for r in rep if r["trigger"] == "glp1_rapid_lean_loss")
    assert o["advices"] == 11 and o["valid"] is True, o
    print("\nDEMO OK — log -> follow-up -> rollup works for both tracks. Wire FOLLOW-UP to live CGM/InBody when the token lands.")

if __name__ == "__main__":
    demo()
