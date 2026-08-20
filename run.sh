#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
dc() { docker compose -f docker-compose.dev.yml "$@"; }

CORE=(aihealth-api aihealth-postgres aihealth-pgbouncer aihealth-mongo
      aihealth-redis aihealth-clickhouse aihealth-qdrant aihealth-arq-redis)
WORKERS=(aihealth-arq-worker aihealth-arq-worker-reports aihealth-arq-worker-vectors
         aihealth-arq-worker-libreview aihealth-arq-worker-instant)
TOOLS=(pgadmin redisinsight mongo-express cloudbeaver portainer)
OBS=(langfuse-server langfuse-db loki promtail grafana)
TUNNEL=(cloudflared)

usage() {
  cat <<'EOF'
Usage: ./run.sh [flags]

Core always starts (api, postgres, pgbouncer, mongo, redis, clickhouse,
qdrant, arq-redis). Flags add optional groups:

  --workers         ARQ workers
  --tools           pgadmin, redisinsight, mongo-express, cloudbeaver, portainer
  --obs             langfuse, loki, promtail, grafana
  --tunnel          cloudflared
  --all             every group
  --only <svc>      start just one service (+ its deps)
  --build           rebuild images before starting
  --down            stop and remove the stack
  --logs [svc]      follow logs (all, or one service)
  --dry             print the docker compose command, don't run it
  -h, --help        this help

No flags -> interactive prompt (defaults: workers + tools).
EOF
}

services=("${CORE[@]}")
build="" only="" action="up" dry=""

if [[ $# -eq 0 ]]; then
  ask() { local ans; read -rp "$1 " ans; [[ "${ans:-$2}" =~ ^[Yy] ]]; }
  ask "Run workers?        [Y/n]" y && services+=("${WORKERS[@]}")
  ask "Run dev tools?      [Y/n]" y && services+=("${TOOLS[@]}")
  ask "Run observability?  [y/N]" n && services+=("${OBS[@]}")
  ask "Run tunnel?         [y/N]" n && services+=("${TUNNEL[@]}")
else
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --workers) services+=("${WORKERS[@]}");;
      --tools)   services+=("${TOOLS[@]}");;
      --obs)     services+=("${OBS[@]}");;
      --tunnel)  services+=("${TUNNEL[@]}");;
      --all)     services+=("${WORKERS[@]}" "${TOOLS[@]}" "${OBS[@]}" "${TUNNEL[@]}");;
      --only)    only="$2"; shift;;
      --build)   build="--build";;
      --down)    action="down";;
      --logs)    action="logs"; only="${2:-}"; [[ -n "$only" ]] && shift || true;;
      --dry)     dry="1";;
      -h|--help) usage; exit 0;;
      *) echo "unknown flag: $1" >&2; usage; exit 1;;
    esac
    shift
  done
fi

case "$action" in
  down) cmd=(down);;
  logs) cmd=(logs -f ${only:+"$only"});;
  up)   if [[ -n "$only" ]]; then set -- up -d ${build:+"$build"} "$only"
        else set -- up -d ${build:+"$build"} "${services[@]}"; fi
        cmd=("$@");;
esac

if [[ -n "$dry" ]]; then echo "docker compose -f docker-compose.dev.yml ${cmd[*]}"; exit 0; fi
dc "${cmd[@]}"
