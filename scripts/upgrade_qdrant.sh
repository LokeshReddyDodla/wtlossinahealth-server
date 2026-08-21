#!/usr/bin/env bash
# Usage: snapshot the collection, then run on the host next to docker-compose.yml.
set -euo pipefail

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

VERSIONS=(v1.11.5 v1.12.6 v1.13.6 v1.14.1 v1.15.5 v1.16.3 v1.17.1 v1.18.3 v1.19.0)
COLLECTION=patient_data
QDRANT_URL=http://localhost:6333
# v1.18.x storage migration runs at boot
MAX_WAIT_SECONDS=3600

wait_healthy() {
  local waited=0 ok_polls=0
  while true; do
    status=$(curl -sf --max-time 5 "$QDRANT_URL/collections/$COLLECTION" \
      | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print(r["status"], json.dumps(r["optimizer_status"]))' \
      2>/dev/null || echo "down")
    case "$status" in
      "green "*) ok_polls=$((ok_polls+1)) ;;
      "yellow \"ok\"") ok_polls=$((ok_polls+1)) ;;
      *) ok_polls=0 ;;
    esac
    if [ "$ok_polls" -ge 3 ]; then return 0; fi
    if [ "$waited" -ge "$MAX_WAIT_SECONDS" ]; then
      echo "TIMED OUT waiting for healthy collection (last: $status)" >&2
      return 1
    fi
    echo "  waiting... ($status)"
    sleep 10; waited=$((waited+10))
  done
}

for v in "${VERSIONS[@]}"; do
  echo "=== upgrading to $v"
  QDRANT_VERSION="$v" $COMPOSE up -d aihealth-qdrant
  wait_healthy
  echo "=== $v healthy"
done

echo "Done. Pin the final version: add QDRANT_VERSION=${VERSIONS[-1]} to .env"
