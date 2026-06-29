"""
Render — turns an engine contract into a constrained, fact-pinned prompt the LLM narrates.

Code pins the grounded facts and locks the template by mode; the LLM writes only the warm words.
"""


def build_prompt(contract):
    m = contract["output_mode"]; pr = contract["prediction"]; lev = contract.get("lever") or {}
    base = ["SYSTEM: AiHealth coach. Render the FINDING into 2-3 warm sentences. Use ONLY the facts below;",
            "do not add advice or numbers that are not here. Output the patient message only."]
    if m == "SAFETY":
        base += ["MODE: SAFETY (no food/activity/dose advice).",
                 "FINDING: pre-meal glucose is low. One move: treat the low first (15g fast carb, recheck in 15 min).",
                 "TONE: gentle, prompt."]
    elif m == "SUGGEST":
        base += ["MODE: SUGGEST.",
                 "FINDING: observed rise +%d mg/dL (use this exact number). attribution: meal-driven." % round(pr["rise_mgdl"]),
                 "ONE MOVE: %s  [cite: %s]  (include the citation token)." % (lev.get("say", ""), lev.get("cite", "")),
                 "TONE: data-driven."]
    elif m == "FLAG_PHYSIOLOGY":
        base += ["MODE: FLAG_PHYSIOLOGY (this rise is NOT the meal; do not tell them to change the food).",
                 "FINDING: %s" % contract["fact"],
                 "TONE: reassuring, explain it is physiology, point them to the care team."]
    else:
        base += ["MODE: %s (state the fact, no new advice)." % m, "FINDING: %s" % contract["fact"], "TONE: warm."]
    return "\n".join(base)
