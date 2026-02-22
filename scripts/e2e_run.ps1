param(
  [string]$EnvFile = ".env",
  [string]$InfraCompose = "docker-compose.infrastructure.yml",
  [string]$TopicsFile = "kafka/topics.yml",
  [string]$CollectorCompose = "rbc_telegram_collector/docker-compose.yml",
  [string]$CollectorDataDir = "rbc_telegram_collector/data",
  [int]$MaxPublish = 0,
  [switch]$OnlyTopics,
  [switch]$StartProcessors,
  [switch]$RunCollector,
  [switch]$PublishJsonl,
  [switch]$StorageChecks
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

function Wait-Healthy($container, $timeoutSec = 420) {
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
  $lines = Get-Content $path
  $start = $null
  $end = $null
  for ($i = 0; $i -lt $lines.Count; $i++) {
    $clean = $lines[$i].Split("#")[0].Trim()
    if ($null -eq $start -and $clean -match "^topics:\s*$") {
      $start = $i + 1
      continue
    }
    if ($null -ne $start -and $clean -match "^consumer_groups:\s*$") {
      $end = $i - 1
      break
    }
  }
  if ($null -eq $start) { return @() }
  if ($null -eq $end) { $end = $lines.Count - 1 }

  $topics = @()
  $current = $null
  for ($i = $start; $i -le $end; $i++) {
    $clean = $lines[$i].Split("#")[0].Trim()
    if ($clean -eq "") { continue }
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

function Start-Infrastructure() {
  Write-Info "Starting infrastructure"
  & docker compose -f $InfraCompose up -d
  & docker compose -f $InfraCompose ps

  Write-Info "Waiting for healthchecks"
  @(
    "telegram-news-postgres",
    "telegram-news-neo4j",
    "telegram-news-zookeeper",
    "telegram-news-kafka",
    "telegram-news-kafka-ui",
    "telegram-news-redis"
  ) | ForEach-Object { Wait-Healthy $_ 420 }
}

function Initialize-Storage() {
  $DbName = $env:DB_NAME; if (-not $DbName) { $DbName = "telegram_news" }
  $DbUser = $env:DB_USER; if (-not $DbUser) { $DbUser = "postgres" }
  $DbPassword = $env:DB_PASSWORD
  $Neo4jPassword = $env:NEO4J_PASSWORD

  if (-not $DbPassword) { throw "DB_PASSWORD is required (set in .env)" }
  if (-not $Neo4jPassword) { throw "NEO4J_PASSWORD is required (set in .env)" }

  Write-Info "Initialize Postgres schema"
  $exists = & docker exec -i telegram-news-postgres psql -U $DbUser -d $DbName -tAc "SELECT to_regclass('public.raw_messages');"
  if ($exists -match "raw_messages") {
    Write-Warn "Postgres schema already present. Skipping migration."
  } else {
    & docker exec -i telegram-news-postgres psql -U $DbUser -d $DbName -f /docker-entrypoint-initdb.d/001_initial_schema.sql
    Write-Info "Postgres migration applied"
  }

  Write-Info "Initialize Neo4j schema"
  & docker exec -i telegram-news-neo4j cypher-shell -u neo4j -p $Neo4jPassword -f /var/lib/neo4j/import/init.cypher
}

function Initialize-KafkaTopics() {
  Write-Info "Creating Kafka topics (if missing)"
  $topics = Get-TopicsFromYaml $TopicsFile
  $existing = & docker exec -i telegram-news-kafka kafka-topics --bootstrap-server kafka:9093 --list
  foreach ($topic in $topics) {
    if ($existing -match "^\s*$($topic.name)\s*$") {
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
  Write-Info "Kafka topics:"
  & docker exec -i telegram-news-kafka kafka-topics --bootstrap-server kafka:9093 --list
}

function Start-ProcessorsIfNeeded() {
  if (-not $StartProcessors) {
    Write-Warn "Processor services not started. Use -StartProcessors to enable."
    return
  }
  Write-Info "Starting processor services (message-persister, preprocessor)"
  & docker compose -f $InfraCompose -f message_persister/docker-compose.yml -f preprocessor/docker-compose.yml up -d message-persister preprocessor
  & docker ps --filter "name=message-persister" --filter "name=preprocessor"
}

function Start-CollectorIfNeeded() {
  if (-not $RunCollector) {
    Write-Warn "Collector not started. Use -RunCollector to enable."
    return
  }
  if (-not $env:TG_API_ID -or -not $env:TG_API_HASH) {
    Write-Warn "TG_API_ID/TG_API_HASH not set. Skipping collector run."
    return
  }
  Write-Info "Running collector (config.yaml controls channels/limits)"
  & docker compose -f $CollectorCompose run --rm --build telegram-collector
}

function Convert-MediaType($media) {
  if ($null -eq $media) { return $null }
  $rawType = $null
  if ($media -is [string]) { $rawType = $media }
  if ($media -is [hashtable] -or $media -is [pscustomobject]) { $rawType = $media.type }
  if (-not $rawType) { return $null }
  $lower = $rawType.ToString().ToLowerInvariant()
  if ($lower -match "photo") { return "photo" }
  if ($lower -match "video") { return "video" }
  if ($lower -match "document") { return "document" }
  if ($lower -match "audio") { return "audio" }
  if ($lower -match "voice") { return "voice" }
  if ($lower -match "sticker") { return "sticker" }
  if ($lower -match "animation|gif") { return "animation" }
  return $null
}

function New-RawEvent($item) {
  $channel = $item.channel
  $messageId = $item.message_id
  if (-not $channel -or -not $messageId) { return $null }
  $eventId = "$channel`:$messageId"
  $messageDate = $item.date_utc
  if (-not $messageDate -and $item.raw) { $messageDate = $item.raw.date }
  $mediaType = Convert-MediaType $item.media
  $mediaObj = $null
  if ($mediaType) { $mediaObj = @{ type = $mediaType } }
  return @{
    event_id = $eventId
    event_type = "raw_message"
    event_timestamp = (Get-Date).ToUniversalTime().ToString("o")
    event_version = "v1.0.0"
    source_system = "telegram-collector"
    trace_id = (New-Guid).ToString()
    payload = @{
      message_id = [int64]$messageId
      channel = $channel
      text = $item.text
      date = $messageDate
      views = if ($item.views) { [int]$item.views } else { 0 }
      forwards = if ($item.forwards) { [int]$item.forwards } else { 0 }
      reactions = $null
      media = $mediaObj
      edit_date = $null
      reply_to_message_id = $null
      author = $null
      is_forwarded = $false
      forward_from_channel = $null
    }
  }
}

function Publish-JsonlToKafka() {
  if (-not $PublishJsonl) {
    Write-Warn "JSONL bridge not executed. Use -PublishJsonl to enable."
    return
  }
  if (-not (Test-Path $CollectorDataDir)) {
    Write-Warn "Collector data dir not found: $CollectorDataDir"
    return
  }
  $jsonlFiles = Get-ChildItem $CollectorDataDir -Filter "*.jsonl" | Sort-Object Name
  if (-not $jsonlFiles) {
    Write-Warn "No JSONL files found in $CollectorDataDir"
    return
  }
  $totalCount = 0
  $reachedLimit = $false
  function Send-KafkaMessage($topic, $key, $payload) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "docker"
    $psi.Arguments = "exec -i telegram-news-kafka kafka-console-producer --bootstrap-server kafka:9093 --topic $topic --property parse.key=true --property key.separator=|"
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false

    $proc = [System.Diagnostics.Process]::Start($psi)
    $line = "$key|$payload`n"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($line)
    $proc.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
    $proc.StandardInput.Close()
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0) {
      $err = $proc.StandardError.ReadToEnd()
      throw "kafka-console-producer failed: $err"
    }
  }

  foreach ($jsonl in $jsonlFiles) {
    if ($reachedLimit) { break }
    Write-Info "Publishing JSONL to Kafka from $($jsonl.FullName)"
    $fileCount = 0
    foreach ($line in Get-Content $jsonl.FullName -Encoding UTF8) {
      if ($MaxPublish -gt 0 -and $totalCount -ge $MaxPublish) {
        $reachedLimit = $true
        break
      }
      if (-not $line.Trim()) { continue }
      $item = $line | ConvertFrom-Json
      $rawEvent = New-RawEvent $item
      if ($null -eq $rawEvent) { continue }
      $payload = $rawEvent | ConvertTo-Json -Depth 8 -Compress
      $key = $rawEvent.event_id
      Send-KafkaMessage "raw.telegram.messages" $key $payload
      $fileCount++
      $totalCount++
    }
    Write-Info "Published $fileCount messages from $($jsonl.Name)"
  }
  Write-Info "Published $totalCount messages to raw.telegram.messages"
}

function Get-KafkaLogEndCount($topic) {
  $out = & docker exec -i telegram-news-kafka kafka-run-class kafka.tools.GetOffsetShell --broker-list kafka:9093 --topic $topic --time -1
  if ($LASTEXITCODE -ne 0) { return $null }
  $sum = 0
  foreach ($line in $out) {
    if ($line -match "^[^:]+:\d+:(\d+)$") {
      $sum += [int64]$matches[1]
    }
  }
  return $sum
}

function Summary() {
  Write-Info "Summary"
  Write-Info "Kafka UI: http://localhost:8080"
  Write-Info "Neo4j Browser: http://localhost:7474"
  $rawCount = Get-KafkaLogEndCount "raw.telegram.messages"
  if ($null -ne $rawCount) {
    Write-Info "raw.telegram.messages log-end count (approx): $rawCount"
  }
  Write-Info "Consumer groups / lag:"
  & docker exec -i telegram-news-kafka kafka-consumer-groups --bootstrap-server kafka:9093 --all-groups --describe
}

function Invoke-StorageChecksIfNeeded() {
  if (-not $StorageChecks) { return }
  $DbName = $env:DB_NAME; if (-not $DbName) { $DbName = "telegram_news" }
  $DbUser = $env:DB_USER; if (-not $DbUser) { $DbUser = "postgres" }
  $Neo4jPassword = $env:NEO4J_PASSWORD
  Write-Info "Postgres counts"
  & docker exec -i telegram-news-postgres psql -U $DbUser -d $DbName -c "SELECT count(*) FROM raw_messages;"
  & docker exec -i telegram-news-postgres psql -U $DbUser -d $DbName -c "SELECT count(*) FROM preprocessed_messages;"
  & docker exec -i telegram-news-postgres psql -U $DbUser -d $DbName -c "SELECT count(*) FROM sentiment_results;"
  & docker exec -i telegram-news-postgres psql -U $DbUser -d $DbName -c "SELECT count(*) FROM ner_results;"
  & docker exec -i telegram-news-postgres psql -U $DbUser -d $DbName -c "SELECT count(*) FROM processed_events;"

  if ($Neo4jPassword) {
    Write-Info "Neo4j counts"
    & docker exec -i telegram-news-neo4j cypher-shell -u neo4j -p $Neo4jPassword "MATCH (m:Message) RETURN count(m);"
    & docker exec -i telegram-news-neo4j cypher-shell -u neo4j -p $Neo4jPassword "MATCH (e:Entity) RETURN count(e);"
    & docker exec -i telegram-news-neo4j cypher-shell -u neo4j -p $Neo4jPassword "MATCH (:Entity)-[r:MENTIONS]->(:Message) RETURN count(r);"
  } else {
    Write-Warn "NEO4J_PASSWORD not set; skipping Neo4j checks."
  }
}

Import-DotEnv $EnvFile

if (-not $OnlyTopics) {
  Start-Infrastructure
  Initialize-Storage
}

Initialize-KafkaTopics
Start-ProcessorsIfNeeded
Start-CollectorIfNeeded
Publish-JsonlToKafka
Invoke-StorageChecksIfNeeded
Summary
