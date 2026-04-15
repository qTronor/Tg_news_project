# RUNBOOK: Local bring-up on Windows

This runbook describes how to bring the infrastructure up locally on Windows and run end-to-end smoke checks against the contracts.

## Prerequisites
- Docker Desktop (Linux containers mode).
- PowerShell 5.1+ (Windows PowerShell) or PowerShell 7+.
- Python 3.9+ (recommended for JSON Schema validation).

## Step A — Prepare environment
Create a `.env` file in the repo root with required secrets and ports.

Example `.env`:
```
DB_PASSWORD=postgres
NEO4J_PASSWORD=neo4jpass
AUTH_JWT_SECRET=replace-with-random-hex
TG_API_ID=123456
TG_API_HASH=your-telegram-api-hash
TG_STRING_SESSION=your-telethon-string-session
DB_PORT=5432
NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687
KAFKA_EXTERNAL_PORT=9092
KAFKA_UI_PORT=8080
REDIS_PORT=6379
```

Optional:
```
DB_NAME=telegram_news
DB_USER=postgres
ADMIN_EMAIL=admin@tgnews.local
ADMIN_PASSWORD=Admin123!
```

## Step B — Start infrastructure
```
docker compose -f docker-compose.infrastructure.yml up -d
docker compose -f docker-compose.infrastructure.yml ps
```

Wait until all services are healthy:
- `telegram-news-postgres`
- `telegram-news-kafka`
- `telegram-news-auth`
- `telegram-news-analytics-api`
- `telegram-news-message-persister`
- `telegram-news-collector`

For the user-added Telegram source flow, the minimum useful stack is:
```
docker compose -f docker-compose.infrastructure.yml up -d postgres kafka frontend analytics-api auth-service message-persister telegram-collector
```

## Step C — Initialize storage
### Postgres (apply migrations)
```
docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -f /docker-entrypoint-initdb.d/001_initial_schema.sql
docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -f /docker-entrypoint-initdb.d/003_first_source.sql
docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -f /docker-entrypoint-initdb.d/004_user_telegram_channels.sql
```

### Neo4j (apply constraints/indexes)
```
docker exec -i telegram-news-neo4j cypher-shell -u neo4j -p <NEO4J_PASSWORD> -f /var/lib/neo4j/import/init.cypher
```

## Step D — Create Kafka topics
Kafka in this repo runs as a single broker. Use replication factor = 1.

```
docker exec -i telegram-news-kafka kafka-topics --bootstrap-server kafka:9093 --list
```

For a single topic:
```
docker exec -i telegram-news-kafka kafka-topics --bootstrap-server kafka:9093 \
  --create --topic raw.telegram.messages --partitions 6 --replication-factor 1 \
  --config retention.ms=2592000000 --config compression.type=lz4 \
  --config cleanup.policy=delete --config segment.ms=86400000 \
  --config max.message.bytes=10485760 --config min.insync.replicas=1
```

## Step E — Validate schemas
If `scripts/validate_schemas.sh` does not work on Windows, use Python:
```
python -m pip install jsonschema
python -c "import glob,json;from jsonschema import validate,validators;import sys; \
schemas=sorted(glob.glob('schemas/*.schema.json')); \
errors=0; \
for s in schemas: \
  schema=json.load(open(s,'r',encoding='utf-8')); \
  validators.validator_for(schema).check_schema(schema); \
  ex=s.replace('schemas','examples').replace('.schema.json','.example.json'); \
  print(f'OK schema: {s}'); \
  if glob.os.path.exists(ex): \
    validate(instance=json.load(open(ex,'r',encoding='utf-8')), schema=schema); \
    print(f'OK example: {ex}'); \
print('Validation complete')"
```

## Step F — E2E smoke (Kafka)
Send `examples/raw_message.example.json` to `raw.telegram.messages` with key=`event_id`:
```
$event = Get-Content examples/raw_message.example.json -Raw | ConvertFrom-Json
$eventId = $event.event_id
$payload = (Get-Content examples/raw_message.example.json -Raw)
@("$eventId|$payload") | docker exec -i telegram-news-kafka kafka-console-producer \
  --bootstrap-server kafka:9093 --topic raw.telegram.messages \
  --property parse.key=true --property key.separator="|"
```

Read back one message:
```
docker exec -i telegram-news-kafka kafka-console-consumer \
  --bootstrap-server kafka:9093 --topic raw.telegram.messages \
  --from-beginning --max-messages 1 --property print.key=true \
  --property key.separator="|"
```

Idempotency check will be validated once DB-writing services are online (message should not produce duplicate rows).

## Step G вЂ” Exercise user-added Telegram sources
1. Open `http://localhost:3000/login` and sign in.
2. Open `http://localhost:3000/sources`.
3. Submit a public Telegram channel username or `https://t.me/<username>` link with a start date on or after `2026-01-01`.
4. Watch the status move through `Validating -> Live enabled/Backfilling -> Ready`.
5. Use `Open in feed` once the first data appears.

Collector notes:
- `rbc_telegram_collector/config.yaml` polls every 60 seconds by default.
- The collector validates pending channels with Telethon and publishes both live and backfill events into `raw.telegram.messages`.
- `message-persister` must be running, otherwise `/feed` will not receive persisted raw rows.

## One-command smoke test
Use `scripts/smoke_test.ps1`:
```
powershell -ExecutionPolicy Bypass -File scripts/smoke_test.ps1
```

## Observability (URLs/ports)
- Kafka UI: `http://localhost:8080`
- Neo4j Browser: `http://localhost:7474` (login `neo4j` / `$NEO4J_PASSWORD`)
- Postgres: `localhost:5432`
- Kafka: `localhost:9092`
- Redis: `localhost:6379`
- Zookeeper: `localhost:2181`

## Logs
```
docker compose -f docker-compose.infrastructure.yml logs -f kafka
docker compose -f docker-compose.infrastructure.yml logs -f postgres
docker compose -f docker-compose.infrastructure.yml logs -f neo4j
```

