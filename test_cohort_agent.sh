#!/usr/bin/env bash
# Test the cohort-agent endpoint on your LOCAL Docker (http://localhost:8000).
#
# Prereqs (so it actually runs):
#   1. The image must have openai-agents installed:
#        poetry lock && poetry install
#        docker compose build && docker compose up -d
#   2. OPENAI_API_KEY must be set in the container env (for LiteLLM -> gpt-5.2).
#      Add to your .env / docker-compose environment, then restart.
#
# Usage:  ./test_cohort_agent.sh            # runs the full question set
#         BASE=http://localhost:8000 PHONE=919844272232 ./test_cohort_agent.sh
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
PHONE="${PHONE:-919844272232}"

echo "→ Logging in as care provider ($PHONE) on $BASE"
SEND=$(curl -sS -X POST "$BASE/v1/auth/send-otp" -H "Content-Type: application/json" -d "{\"phone_number\":\"$PHONE\"}")
OTP=$(echo "$SEND" | grep -oE '[0-9]{4,8}' | tail -1)
VR=$(curl -sS -X POST "$BASE/v1/auth/verify-otp?role=care_provider" -H "Content-Type: application/json" -d "{\"phone_number\":\"$PHONE\",\"otp\":\"$OTP\"}")
TOKEN=$(echo "$VR" | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")
DEVICE=$(echo "$VR" | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['device_id'])")
echo "✓ logged in"

ask() {
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo "Q: $1"
  echo "────────────────────────────────────────────────────────────"
  curl -sS -X POST "$BASE/v1/cohort-agent/query" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -H "x-device-id: $DEVICE" \
    -d "$(python3 -c "import json,sys;print(json.dumps({'message':sys.argv[1]}))" "$1")" \
    --max-time 120 \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('data',{}).get('answer') or d.get('detail') or d)"
}

# ── Panel overview ───────────────────────────────────────────────
ask "How many patients are under my care, and what's the age and gender breakdown?"
ask "Who are my 10 most recently active patients?"
ask "Search my patients for anyone named \"Sharma\"."

# ── Glucose / diabetes (CGM) ─────────────────────────────────────
ask "How many of my patients are in the diabetes range by GMI in the last 14 days? List the top 10 with their estimated A1c."
ask "Who is prediabetic (GMI 5.7-6.4%) but not yet diabetic?"
ask "Who had sudden blood-sugar spikes this week, ranked by peak glucose?"
ask "Which patients had hypoglycemic (low) events in the last 30 days?"
ask "Who has the most erratic glucose (highest variability) right now?"
ask "For Tanuja Sridhar, what's her average glucose, time-in-range, and GMI over the last two weeks?"

# ── Meals / engagement ───────────────────────────────────────────
ask "Who logs their meals most regularly this month? Show days-logged out of 30."
ask "How many of my patients logged zero meals in the last month?"
ask "What's the daily meal-logging volume trend over the last 30 days?"
ask "Which patients dropped off - logged regularly early in the month but stopped?"

# ── Cross-analysis ───────────────────────────────────────────────
ask "Cross-reference my diabetes-range patients with meal logging - which diabetics are NOT tracking their food?"
ask "Among patients with glucose spikes, who is also logging meals so I can review what they ate?"
ask "Give me a prioritized list of my 15 highest-risk patients combining high GMI, frequent spikes, and poor logging."

# ── Single-patient deep dive ─────────────────────────────────────
ask "Give me a full update on patient Girish Shirolkar."
ask "What medications is Pankaj Kumar on?"

echo ""
echo "✓ done"
