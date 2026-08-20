# Runbook: local dev stack

The whole stack runs from `docker-compose.dev.yml`. `run.sh` is a thin wrapper
that picks which service groups to start.

## Quick start

```bash
./run.sh                    # interactive: prompts per group (defaults: workers + tools)
./run.sh --workers --tools  # core + those groups, non-interactive
```

Core always starts: `aihealth-api`, `postgres`, `pgbouncer`, `mongo`, `redis`,
`clickhouse`, `qdrant`, `arq-redis`. Everything else is opt-in.

## run.sh flags

| Flag | Effect |
|------|--------|
| _(none)_ | interactive prompt, defaults workers+tools on |
| `--workers` | the 5 ARQ workers |
| `--tools` | pgadmin, redisinsight, mongo-express, cloudbeaver, portainer |
| `--obs` | langfuse, loki, promtail, grafana |
| `--tunnel` | cloudflared |
| `--all` | every group |
| `--only <svc>` | one service + its deps |
| `--build` | rebuild images first |
| `--down` | stop and remove the stack |
| `--logs [svc]` | follow logs (all, or one service) |
| `--dry` | print the `docker compose` command instead of running it |

Service groups are arrays at the top of `run.sh` — add a service to a group by
editing one line.

## Startup ordering

`depends_on` uses `condition: service_healthy`, so a group waits until its
backing stores actually accept connections (not just "container started").
Workers additionally wait for `aihealth-api` to be healthy, because the API runs
schema creation (`create_all`) at boot. Healthchecks live on postgres, mongo,
redis, clickhouse, and the api; qdrant has no shell in its image so it stays
`service_started`.

## Ports

| Service | Host port |
|---------|-----------|
| api | 8000 |
| postgres | 5432 |
| pgbouncer | 6432 |
| mongo | 27017 |
| redis | 6379 |
| arq-redis | 6380 |
| clickhouse | 8123 (http), 9000 (native) |
| qdrant | 6333 (http), 6334 (grpc) |
| pgadmin | 8081 |
| mongo-express | 8082 |
| cloudbeaver | 8084 |
| redisinsight | 5540 |
| grafana | 3000 |
| langfuse | 3001 |
| loki | 3100 |
| portainer | 9001 |

## Common commands

```bash
./run.sh --logs aihealth-api                              # tail one service
docker compose -f docker-compose.dev.yml ps               # status
docker compose -f docker-compose.dev.yml restart aihealth-api
docker compose -f docker-compose.dev.yml exec aihealth-postgres psql -U "$POSTGRES_USER" "$POSTGRES_DB"
```

The API bind-mounts `.:/src`, so Python edits need only a `restart aihealth-api`,
not a rebuild. Rebuild (`--build`) only when dependencies or the Dockerfile change.

## When it won't boot

- ClickHouse `Authentication failed` / crash-loop → see
  [clickhouse-startup-failures.md](clickhouse-startup-failures.md).
- `duplicate key ... pg_type_typname_nsp_index (careproviderstatus)` — two
  gunicorn workers race on `create_all` at boot. Not yet fixed; workaround is a
  single web worker, or serialize schema init.
