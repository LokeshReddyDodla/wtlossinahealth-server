"""
Nudge engine — turns grounded brain signals into ranked, capped patient nudges.

A nudge only fires from a real trigger (a predicted spike, a stale sensor, a safety event,
a twin counterfactual, thin data), never generic spam. Pure stdlib, deterministic.
The engine decides the trigger and the cited fact; the LLM only warms the words.

Design rule: at most 2 nudges per turn, safety always wins, every coaching nudge carries a citation.
"""

P_SAFETY = 100
P_PHYSIOLOGY = 80
P_FRESHNESS = 90
P_SPIKE = 70
P_TWIN = 60
P_COLD_START = 40
P_REINFORCE = 30

from lib.ai_foundation.config import settings

CGM_STALE_DAYS = settings.METABOLIC_CGM_STALE_DAYS
MAX_NUDGES = settings.METABOLIC_MAX_NUDGES


def _n(trigger, priority, text, cite=None, channel="whatsapp", urgent=False):
    return {"trigger": trigger, "priority": priority, "text": text,
            "cite": cite, "channel": channel, "urgent": urgent}


def build_nudges(contract=None, signals=None, twin_levers=None, cgm_age_days=None):
    """
    contract     : engine contract (output_mode, lever, attribution, fact, ...) or None.
    signals      : data-availability dict (e.g. {"cold_start": bool}) or None.
    twin_levers  : list of {"say","effect_mgdl","cite"} from the metabolic twin, or None.
    cgm_age_days : age in days of the latest CGM reading, or None if unknown.
    Returns a ranked, capped list of nudge dicts. Safety always survives the cap.
    """
    out = []
    c = contract or {}
    mode = c.get("output_mode")
    lever = c.get("lever") or {}

    if mode == "SAFETY":
        out.append(_n("safety", P_SAFETY,
                      "Your glucose looks low. Treat it first (about 15g fast carb, recheck in 15 min) and contact your care team if it persists.",
                      cite="safety_protocol", urgent=True))

    if cgm_age_days is not None and cgm_age_days > CGM_STALE_DAYS:
        out.append(_n("freshness", P_FRESHNESS,
                      "Your sensor has been dark for %d days. Reconnect it so I can coach the week you are actually having." % int(cgm_age_days),
                      cite="data_freshness"))

    if mode == "FLAG_PHYSIOLOGY":
        sig = (c.get("attribution") or {}).get("physiology_signal")
        out.append(_n("physiology", P_PHYSIOLOGY,
                      ("This rise looks like your physiology, not the meal. " + (sig + ". " if sig else "")) + "Worth discussing the pattern with your care team.",
                      cite="attribution"))

    if mode == "SUGGEST" and lever.get("cite"):
        eff = lever.get("effect_mgdl")
        tail = (" (about %d mg/dL lower)" % abs(round(eff))) if isinstance(eff, (int, float)) else ""
        out.append(_n("predicted_spike", P_SPIKE,
                      "This meal is likely to spike you. Try: %s%s." % (lever.get("say", ""), tail),
                      cite=lever.get("cite")))

    if twin_levers:
        best = max(twin_levers, key=lambda l: abs(l.get("effect_mgdl", 0)))
        if abs(best.get("effect_mgdl", 0)) >= 5:
            out.append(_n("twin_counterfactual", P_TWIN,
                          "If you %s, your spike would likely drop about %d mg/dL." % (best.get("say", "adjust this meal"), abs(round(best["effect_mgdl"]))),
                          cite=best.get("cite", "metabolic_twin")))

    if (signals or {}).get("cold_start"):
        out.append(_n("cold_start", P_COLD_START,
                      "Log a few more meals with your sensor on and I can give you your own numbers instead of general guidance.",
                      cite="data_sufficiency"))

    if mode == "REINFORCE":
        out.append(_n("reinforce", P_REINFORCE,
                      "Nicely balanced and well in range. Keep doing what you are doing.",
                      cite="in_range"))

    out.sort(key=lambda x: -x["priority"])
    capped = out[:MAX_NUDGES]
    if any(x["trigger"] == "safety" for x in out) and not any(x["trigger"] == "safety" for x in capped):
        capped = [next(x for x in out if x["trigger"] == "safety")] + capped[:MAX_NUDGES - 1]
    return capped
