param(
    [string]$InputPath = "docs/minimal_sentiment_output.jsonl",
    [string]$PostgresContainer = "telegram-news-postgres",
    [string]$Database = "telegram_news",
    [string]$User = "postgres",
    [string]$ModelVersion = "manual-gpt-output-2026-04-21"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $InputPath)) {
    throw "Input file not found: $InputPath"
}

$labels = @("positive", "negative", "neutral")
$emotionNames = @("anger", "fear", "joy", "sadness", "surprise", "disgust")
$invariantCulture = [System.Globalization.CultureInfo]::InvariantCulture
$rows = New-Object System.Collections.Generic.List[object]
$lineNumber = 0
$errors = New-Object System.Collections.Generic.List[string]

function Test-Probability {
    param(
        [object]$Value,
        [string]$Name,
        [int]$Line
    )
    if ($null -eq $Value) {
        $errors.Add("line ${Line}: missing ${Name}")
        return $false
    }
    $number = [double]$Value
    if ($number -lt 0 -or $number -gt 1) {
        $errors.Add("line ${Line}: ${Name} out of range: ${number}")
        return $false
    }
    return $true
}

function Format-Probability {
    param([double]$Value)
    return ([math]::Round($Value, 4)).ToString("0.####", $invariantCulture)
}

Get-Content -LiteralPath $InputPath -Encoding UTF8 | ForEach-Object {
    $lineNumber += 1
    $line = $_
    if ([string]::IsNullOrWhiteSpace($line)) {
        return
    }

    try {
        $obj = $line | ConvertFrom-Json
    } catch {
        $errors.Add("line ${lineNumber}: invalid JSON: $($_.Exception.Message)")
        return
    }

    foreach ($field in @("request_id", "event_id", "preprocessed_message_id", "channel", "message_id", "sentiment")) {
        if ($null -eq $obj.$field -or [string]::IsNullOrWhiteSpace([string]$obj.$field)) {
            $errors.Add("line ${lineNumber}: missing ${field}")
        }
    }

    if ($null -ne $obj.sentiment -and $labels -notcontains $obj.sentiment.label) {
        $errors.Add("line ${lineNumber}: invalid sentiment label: $($obj.sentiment.label)")
    }

    foreach ($field in @("score", "positive_prob", "negative_prob", "neutral_prob")) {
        if ($null -ne $obj.sentiment) {
            [void](Test-Probability $obj.sentiment.$field "sentiment.${field}" $lineNumber)
        }
    }

    $emotion = @{}
    foreach ($name in $emotionNames) {
        $value = 0.0
        if ($null -ne $obj.emotions -and $null -ne $obj.emotions.$name) {
            $value = [double]$obj.emotions.$name
        }
        if ($value -lt 0 -or $value -gt 1) {
            $errors.Add("line ${lineNumber}: emotions.${name} out of range: ${value}")
        }
        $emotion[$name] = [math]::Round($value, 4)
    }

    $aspectsJson = "[]"
    if ($null -ne $obj.aspects) {
        foreach ($aspect in @($obj.aspects)) {
            if ($null -eq $aspect.aspect -or $labels -notcontains $aspect.sentiment) {
                $errors.Add("line ${lineNumber}: invalid aspect object")
            }
            if ($null -ne $aspect.score) {
                [void](Test-Probability $aspect.score "aspect.score" $lineNumber)
            }
        }
        $aspectsJson = ConvertTo-Json -InputObject @($obj.aspects) -Depth 10 -Compress
    }

    $rows.Add([pscustomobject]@{
        request_id = [string]$obj.request_id
        event_id = [string]$obj.event_id
        preprocessed_message_id = [string]$obj.preprocessed_message_id
        channel = [string]$obj.channel
        message_id = [int64]$obj.message_id
        sentiment_label = [string]$obj.sentiment.label
        sentiment_score = Format-Probability ([double]$obj.sentiment.score)
        positive_prob = Format-Probability ([double]$obj.sentiment.positive_prob)
        negative_prob = Format-Probability ([double]$obj.sentiment.negative_prob)
        neutral_prob = Format-Probability ([double]$obj.sentiment.neutral_prob)
        emotion_anger = Format-Probability ([double]$emotion["anger"])
        emotion_fear = Format-Probability ([double]$emotion["fear"])
        emotion_joy = Format-Probability ([double]$emotion["joy"])
        emotion_sadness = Format-Probability ([double]$emotion["sadness"])
        emotion_surprise = Format-Probability ([double]$emotion["surprise"])
        emotion_disgust = Format-Probability ([double]$emotion["disgust"])
        aspects = $aspectsJson
    })
}

if ($errors.Count -gt 0) {
    $errors | Select-Object -First 50 | ForEach-Object { Write-Error $_ }
    throw "Validation failed with $($errors.Count) error(s)"
}

if ($rows.Count -eq 0) {
    throw "No rows to import"
}

$importDir = "exports"
New-Item -ItemType Directory -Force -Path $importDir | Out-Null
$csvPath = Join-Path $importDir "gpt_minimal_sentiment_stage.csv"
$sqlPath = Join-Path $importDir "gpt_minimal_sentiment_import.sql"

$rows | Export-Csv -LiteralPath $csvPath -NoTypeInformation -Encoding UTF8

$containerCsvPath = "/tmp/gpt_minimal_sentiment_stage.csv"
docker cp $csvPath "${PostgresContainer}:${containerCsvPath}"

$sql = @"
\set ON_ERROR_STOP on
CREATE TEMP TABLE gpt_minimal_sentiment_stage (
    request_id text,
    event_id varchar(512),
    preprocessed_message_id uuid,
    channel varchar(255),
    message_id bigint,
    sentiment_label varchar(50),
    sentiment_score real,
    positive_prob real,
    negative_prob real,
    neutral_prob real,
    emotion_anger real,
    emotion_fear real,
    emotion_joy real,
    emotion_sadness real,
    emotion_surprise real,
    emotion_disgust real,
    aspects jsonb
);
\copy gpt_minimal_sentiment_stage (request_id, event_id, preprocessed_message_id, channel, message_id, sentiment_label, sentiment_score, positive_prob, negative_prob, neutral_prob, emotion_anger, emotion_fear, emotion_joy, emotion_sadness, emotion_surprise, emotion_disgust, aspects) FROM '$containerCsvPath' WITH (FORMAT csv, HEADER true);

DO `$`$
DECLARE
    missing_count integer;
BEGIN
    SELECT count(*)
    INTO missing_count
    FROM gpt_minimal_sentiment_stage s
    LEFT JOIN preprocessed_messages pm
      ON pm.id = s.preprocessed_message_id
     AND pm.channel = s.channel
     AND pm.message_id = s.message_id
     AND pm.event_id = s.event_id
    WHERE pm.id IS NULL;

    IF missing_count > 0 THEN
        RAISE EXCEPTION 'stage rows without matching preprocessed_messages: %', missing_count;
    END IF;
END
`$`$;

INSERT INTO sentiment_results (
    preprocessed_message_id,
    message_id,
    channel,
    event_id,
    sentiment_label,
    sentiment_score,
    positive_prob,
    negative_prob,
    neutral_prob,
    emotion_anger,
    emotion_fear,
    emotion_joy,
    emotion_sadness,
    emotion_surprise,
    emotion_disgust,
    aspects,
    model_name,
    model_version,
    model_framework,
    event_timestamp,
    trace_id,
    processing_time_ms,
    analyzed_at
)
SELECT
    s.preprocessed_message_id,
    s.message_id,
    s.channel,
    s.event_id,
    s.sentiment_label,
    s.sentiment_score,
    s.positive_prob,
    s.negative_prob,
    s.neutral_prob,
    s.emotion_anger,
    s.emotion_fear,
    s.emotion_joy,
    s.emotion_sadness,
    s.emotion_surprise,
    s.emotion_disgust,
    s.aspects,
    'gpt-manual-minimal-analysis',
    '$ModelVersion',
    'openai',
    COALESCE(pm.event_timestamp, NOW()),
    pm.trace_id,
    NULL,
    NOW()
FROM gpt_minimal_sentiment_stage s
JOIN preprocessed_messages pm
  ON pm.id = s.preprocessed_message_id
 AND pm.channel = s.channel
 AND pm.message_id = s.message_id
 AND pm.event_id = s.event_id
ON CONFLICT (channel, message_id) DO UPDATE
SET preprocessed_message_id = EXCLUDED.preprocessed_message_id,
    event_id = EXCLUDED.event_id,
    sentiment_label = EXCLUDED.sentiment_label,
    sentiment_score = EXCLUDED.sentiment_score,
    positive_prob = EXCLUDED.positive_prob,
    negative_prob = EXCLUDED.negative_prob,
    neutral_prob = EXCLUDED.neutral_prob,
    emotion_anger = EXCLUDED.emotion_anger,
    emotion_fear = EXCLUDED.emotion_fear,
    emotion_joy = EXCLUDED.emotion_joy,
    emotion_sadness = EXCLUDED.emotion_sadness,
    emotion_surprise = EXCLUDED.emotion_surprise,
    emotion_disgust = EXCLUDED.emotion_disgust,
    aspects = EXCLUDED.aspects,
    model_name = EXCLUDED.model_name,
    model_version = EXCLUDED.model_version,
    model_framework = EXCLUDED.model_framework,
    event_timestamp = EXCLUDED.event_timestamp,
    trace_id = EXCLUDED.trace_id,
    processing_time_ms = EXCLUDED.processing_time_ms,
    analyzed_at = EXCLUDED.analyzed_at;

SELECT
    count(*) AS imported_rows,
    count(*) FILTER (WHERE sentiment_label = 'positive') AS positive,
    count(*) FILTER (WHERE sentiment_label = 'negative') AS negative,
    count(*) FILTER (WHERE sentiment_label = 'neutral') AS neutral
FROM sentiment_results
WHERE model_name = 'gpt-manual-minimal-analysis'
  AND model_version = '$ModelVersion';
"@

Set-Content -LiteralPath $sqlPath -Value $sql -Encoding UTF8

Get-Content -LiteralPath $sqlPath -Encoding UTF8 |
    docker exec -i $PostgresContainer psql -U $User -d $Database -P pager=off -F '|' -A -f -
