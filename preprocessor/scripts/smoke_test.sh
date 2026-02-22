#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RAW_EXAMPLE="${ROOT_DIR}/examples/raw_message.example.json"

if [[ ! -f "${RAW_EXAMPLE}" ]]; then
  echo "Missing examples/raw_message.example.json"
  exit 1
fi

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

echo "Sending raw event_id=${EVENT_ID}"
echo "${EVENT_ID}|${EVENT_JSON}" | docker exec -i telegram-news-kafka \
  kafka-console-producer --bootstrap-server localhost:9092 \
  --topic raw.telegram.messages --property parse.key=true --property key.separator="|"

echo "Waiting for preprocessed output..."
docker exec -it telegram-news-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic preprocessed.messages \
  --from-beginning --max-messages 1 --property print.key=true --property key.separator="|"

echo "Latest DB row:"
docker exec -it telegram-news-postgres \
  psql -U "${DB_USER:-postgres}" -d "${DB_NAME:-telegram_news}" \
  -c "select channel, message_id, word_count, created_at from preprocessed_messages order by created_at desc limit 1;"
