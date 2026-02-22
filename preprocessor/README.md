## Preprocessor service

Consumes `raw.telegram.messages` and `persisted.messages`, validates JSON Schema,
preprocesses text, writes into `preprocessed_messages`, and publishes
`preprocessed.messages`. Idempotency is enforced via `processed_events` and
`preprocessed_messages` unique constraint.

### Config

By default the compose file mounts `config.example.yaml` as `config.yaml`.
If you need custom settings, copy `config.example.yaml` to `config.yaml`,
update values, and switch the volume mapping in `preprocessor/docker-compose.yml`.

- Kafka: input/output topics and DLQ
- Postgres connection
- Ports for `/healthz` and `/metrics`

Environment variables override YAML with prefix `PREPROCESSOR__`.

### Run with infrastructure

From repo root:

```
docker compose -f docker-compose.infrastructure.yml -f preprocessor/docker-compose.yml up --build
```

### Smoke test

You can use the included script (requires Docker + Python on host):

```
bash preprocessor/scripts/smoke_test.sh
```

Manual version (send one raw example and read output):

```
EVENT_ID="$(python - <<'PY'
import json
with open("examples/raw_message.example.json", "r", encoding="utf-8") as f:
    payload = json.load(f)
print(payload["event_id"])
PY
)"
EVENT_JSON="$(python - <<'PY'
import json
with open("examples/raw_message.example.json", "r", encoding="utf-8") as f:
    payload = json.load(f)
print(json.dumps(payload, ensure_ascii=False))
PY
)"
echo "${EVENT_ID}|${EVENT_JSON}" | docker exec -i telegram-news-kafka \
  kafka-console-producer --bootstrap-server localhost:9092 \
  --topic raw.telegram.messages --property parse.key=true --property key.separator="|"

docker exec -it telegram-news-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic preprocessed.messages \
  --from-beginning --max-messages 1 --property print.key=true --property key.separator="|"

docker exec -it telegram-news-postgres \
  psql -U ${DB_USER:-postgres} -d ${DB_NAME:-telegram_news} \
  -c "select channel, message_id, word_count, created_at from preprocessed_messages order by created_at desc limit 1;"
```
