# Telegram collector (RBC + any channels)

Service for exporting posts from public Telegram channels via MTProto using Telethon.
Every run collects the last 3 calendar days and publishes raw events to Kafka so `message-persister` can persist them into Postgres.

## Quick start

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
cp config.example.yaml config.yaml
```

### Telegram API access

You need `api_id` and `api_hash` from <https://my.telegram.org>.
Set them as environment variables:

```bash
# Windows PowerShell:
$env:TG_API_ID="123456"
$env:TG_API_HASH="0123456789abcdef0123456789abcdef"
```

If Telegram must be reached through a proxy, set:

```bash
$env:TG_PROXY_ENABLED="true"
$env:TG_PROXY_SCHEME="socks5"
$env:TG_PROXY_HOST="proxy.example.com"
$env:TG_PROXY_PORT="1080"
# Optional:
# $env:TG_PROXY_USERNAME="user"
# $env:TG_PROXY_PASSWORD="secret"
# $env:TG_PROXY_RDNS="true"
```

### One-shot collection

The first run may ask for phone and login code and then create a local `.session` file.

```bash
python -m collector.cli collect --config config.yaml
```

### Scheduled service mode

The default config already enables:

```yaml
collection:
  lookback_days: 3

kafka:
  enabled: true
  topic: raw.telegram.messages

scheduler:
  enabled: true
  interval_seconds: 3600
```

Start the long-running service:

```bash
python -m collector.cli service --config config.yaml
```

The service runs one collection cycle immediately after startup and then repeats it on the configured interval.

### StringSession for non-interactive runs

Generate a reusable string session locally:

```bash
python -m collector.cli make-session
```

Save the printed value into `TG_STRING_SESSION` and use it for server or container runs.
`make-session` uses the same `TG_PROXY_*` variables, so the login handshake can also go through the proxy.

## Output

The collector writes `data/<channel>.jsonl` for the current lookback window and also publishes the same messages to Kafka.

## Adding channels

Open `config.yaml` and add more items under `channels`.

## Docker Compose

1. Create `.env` in this project folder:

```bash
TG_API_ID=your_api_id_here
TG_API_HASH=your_api_hash_here
# Optional:
# TG_STRING_SESSION=your_string_session_here
# TG_PROXY_ENABLED=true
# TG_PROXY_SCHEME=socks5
# TG_PROXY_HOST=proxy.example.com
# TG_PROXY_PORT=1080
```

2. Make sure `config.yaml` exists.
3. Run:

```bash
docker-compose up
```

This compose file starts the collector in scheduled service mode and publishes raw events to Kafka via `host.docker.internal:9092`.
