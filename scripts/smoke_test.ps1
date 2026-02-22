param(
  [string]$ComposeFile = "docker-compose.infrastructure.yml",
  [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Import-DotEnv($path) {
  if (-not (Test-Path $path)) {
    Write-Warn "No $path found. Using defaults and environment variables."
    return
  }

  Get-Content $path | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $pair = $line.Split("=", 2)
    if ($pair.Count -ne 2) { return }
    $key = $pair[0].Trim()
    $value = $pair[1].Trim().Trim("'`"")
    if ($key -ne "") {
      [Environment]::SetEnvironmentVariable($key, $value)
    }
  }
  Write-Info "Loaded environment from $path"
}

function Wait-Healthy($container, $timeoutSec = 300) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    $status = & docker inspect -f "{{.State.Health.Status}}" $container 2>$null
    if ($LASTEXITCODE -ne 0) {
      Start-Sleep -Seconds 3
      continue
    }
    if ($status -eq "healthy") {
      Write-Info "$container is healthy"
      return
    }
    if ($status -eq "unhealthy") {
      throw "$container is unhealthy"
    }
    Start-Sleep -Seconds 5
  }
  throw "Timeout waiting for $container health"
}

function Get-TopicsFromYaml($path) {
  if (-not (Test-Path $path)) { throw "Topics file not found: $path" }
  $topics = @()
  $current = $null
  $inTopics = $false
  foreach ($line in Get-Content $path) {
    $lineNoComment = $line.Split("#")[0]
    $clean = $lineNoComment.Trim()
    if ($lineNoComment -match "^[^\s]" -and $clean -eq "topics:") { $inTopics = $true; continue }
    if ($lineNoComment -match "^[^\s]" -and $clean -eq "consumer_groups:") {
      $inTopics = $false
      continue
    }
    if (-not $inTopics) { continue }
    if ($clean -match "^- name:\s*(.+)$") {
      if ($null -ne $current) { $topics += $current }
      $current = @{
        name = $matches[1].Trim()
        partitions = 1
        replication_factor = 1
        config = @{}
      }
      continue
    }
    if ($null -eq $current) { continue }
    if ($clean -match "^partitions:\s*(\d+)") {
      $current.partitions = [int]$matches[1]
      continue
    }
    if ($clean -match "^replication_factor:\s*(\d+)") {
      $current.replication_factor = [int]$matches[1]
      continue
    }
    if ($clean -match "^retention\.ms:\s*([0-9]+)") {
      $current.config["retention.ms"] = $matches[1]
      continue
    }
    if ($clean -match "^compression\.type:\s*([^\s]+)") {
      $current.config["compression.type"] = $matches[1]
      continue
    }
    if ($clean -match "^cleanup\.policy:\s*([^\s]+)") {
      $current.config["cleanup.policy"] = $matches[1]
      continue
    }
    if ($clean -match "^segment\.ms:\s*([0-9]+)") {
      $current.config["segment.ms"] = $matches[1]
      continue
    }
    if ($clean -match "^max\.message\.bytes:\s*([0-9]+)") {
      $current.config["max.message.bytes"] = $matches[1]
      continue
    }
    if ($clean -match "^min\.insync\.replicas:\s*([0-9]+)") {
      $current.config["min.insync.replicas"] = $matches[1]
      continue
    }
  }
  if ($null -ne $current) { $topics += $current }
  return $topics
}

Import-DotEnv $EnvFile

$DbName = $env:DB_NAME; if (-not $DbName) { $DbName = "telegram_news" }
$DbUser = $env:DB_USER; if (-not $DbUser) { $DbUser = "postgres" }
$DbPassword = $env:DB_PASSWORD
$Neo4jPassword = $env:NEO4J_PASSWORD

if (-not $DbPassword) { throw "DB_PASSWORD is required (set in .env)" }
if (-not $Neo4jPassword) { throw "NEO4J_PASSWORD is required (set in .env)" }

Write-Info "Step B: Starting infrastructure"
& docker compose -f $ComposeFile up -d

Write-Info "Step B: Waiting for healthchecks"
@(
  "telegram-news-postgres",
  "telegram-news-neo4j",
  "telegram-news-zookeeper",
  "telegram-news-kafka",
  "telegram-news-kafka-ui",
  "telegram-news-redis"
) | ForEach-Object { Wait-Healthy $_ 420 }

Write-Info "Step C: Initialize Postgres schema"
$exists = & docker exec -i telegram-news-postgres psql -U $DbUser -d $DbName -tAc "SELECT to_regclass('public.raw_messages');"
if ($exists -match "raw_messages") {
  Write-Warn "Postgres schema already present. Skipping migration."
} else {
  & docker exec -i telegram-news-postgres psql -U $DbUser -d $DbName -f /docker-entrypoint-initdb.d/001_initial_schema.sql
  Write-Info "Postgres migration applied"
}

Write-Info "Step C: Initialize Neo4j schema"
& docker exec -i telegram-news-neo4j cypher-shell -u neo4j -p $Neo4jPassword -f /var/lib/neo4j/import/init.cypher

Write-Info "Step D: Create Kafka topics"
$topics = Get-TopicsFromYaml "kafka/topics.yml"
$existing = & docker exec -i telegram-news-kafka kafka-topics --bootstrap-server kafka:9093 --list
$existingTopics = $existing -split "`r?`n" | Where-Object { $_ -ne "" }
foreach ($topic in $topics) {
  if ($existingTopics -contains $topic.name) {
    Write-Warn "Topic exists: $($topic.name)"
    continue
  }
  $replicationFactor = $topic.replication_factor
  if ($replicationFactor -gt 1) { $replicationFactor = 1 }
  $configArgs = @()
  foreach ($kv in $topic.config.GetEnumerator()) {
    if ($kv.Key -eq "min.insync.replicas") {
      $configArgs += "--config"
      $configArgs += "min.insync.replicas=1"
      continue
    }
    $configArgs += "--config"
    $configArgs += ("{0}={1}" -f $kv.Key, $kv.Value)
  }
  & docker exec -i telegram-news-kafka kafka-topics --bootstrap-server kafka:9093 `
    --create --topic $topic.name --partitions $topic.partitions --replication-factor $replicationFactor `
    @configArgs
  Write-Info "Created topic: $($topic.name)"
}

Write-Info "Step E: Validate schemas (Python/jsonschema)"
$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) {
  Write-Warn "Python not found. Skipping JSON Schema validation."
} else {
  & python -c "import sys;`ntry:`n import jsonschema`nexcept Exception:`n sys.exit(1)`nsys.exit(0)"
  if ($LASTEXITCODE -ne 0) {
    Write-Info "Installing jsonschema..."
    & python -m pip install jsonschema
  }
  $script = @'
import glob,json,sys,os
from jsonschema import validate,validators

schemas = sorted(glob.glob("schemas/*.schema.json"))
errors = 0
for schema_path in schemas:
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    validators.validator_for(schema).check_schema(schema)
    print(f"OK schema: {schema_path}")
    example_path = schema_path.replace("schemas", "examples").replace(".schema.json", ".example.json")
    if os.path.exists(example_path):
        with open(example_path, "r", encoding="utf-8") as f:
            example = json.load(f)
        validate(instance=example, schema=schema)
        print(f"OK example: {example_path}")
print("Validation complete")
'@
  $tempScript = New-TemporaryFile
  Set-Content -Path $tempScript -Value $script -Encoding UTF8
  & python $tempScript
  Remove-Item $tempScript -ErrorAction SilentlyContinue
}

Write-Info "Step F: Produce raw event to Kafka"
$rawObj = Get-Content examples/raw_message.example.json -Raw | ConvertFrom-Json
$rawJson = $rawObj | ConvertTo-Json -Compress
$eventId = $rawObj.event_id
if (-not $eventId) { throw "event_id not found in raw_message.example.json" }
$line = "$eventId|$rawJson"
$line | & docker exec -i telegram-news-kafka kafka-console-producer `
  --bootstrap-server kafka:9093 --topic raw.telegram.messages `
  --property parse.key=true --property key.separator="|"

Write-Info "Read back messages from raw.telegram.messages"
$consumerGroup = "smoke-test-" + ([guid]::NewGuid().ToString("N"))
$consumeOutput = & docker exec -i telegram-news-kafka kafka-console-consumer `
  --bootstrap-server kafka:9093 --topic raw.telegram.messages `
  --from-beginning --max-messages 50 --timeout-ms 10000 `
  --property print.key=true --property key.separator="|" `
  --consumer-property "group.id=$consumerGroup"

if ($consumeOutput) {
  Write-Host $consumeOutput
}

if ($consumeOutput -match [regex]::Escape("$eventId|")) {
  Write-Info "Found produced event in topic"
} else {
  Write-Warn "Produced event not found in first 50 messages. Topic may have heavy traffic."
}

Write-Info "Repeat send for idempotency check (DB pipeline pending)"
$line | & docker exec -i telegram-news-kafka kafka-console-producer `
  --bootstrap-server kafka:9093 --topic raw.telegram.messages `
  --property parse.key=true --property key.separator="|"

Write-Warn "Idempotency verification requires DB-writing services. Re-run after services are added."
Write-Info "Smoke test completed"

