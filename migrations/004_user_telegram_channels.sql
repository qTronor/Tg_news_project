-- Migration: 004_user_telegram_channels
-- Description: User-managed Telegram source registry and per-day backfill jobs
-- Date: 2026-04-14

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =====================================================
-- channels operational registry expansion
-- =====================================================
ALTER TABLE channels
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(32),
    ADD COLUMN IF NOT EXISTS input_value VARCHAR(255),
    ADD COLUMN IF NOT EXISTS telegram_url TEXT,
    ADD COLUMN IF NOT EXISTS telegram_channel_id BIGINT,
    ADD COLUMN IF NOT EXISTS added_by_user_id UUID,
    ADD COLUMN IF NOT EXISTS added_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS requested_start_date DATE,
    ADD COLUMN IF NOT EXISTS historical_limit_date DATE,
    ADD COLUMN IF NOT EXISTS status VARCHAR(64),
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS validation_error TEXT,
    ADD COLUMN IF NOT EXISTS live_enabled BOOLEAN,
    ADD COLUMN IF NOT EXISTS backfill_total_days INTEGER,
    ADD COLUMN IF NOT EXISTS backfill_completed_days INTEGER,
    ADD COLUMN IF NOT EXISTS backfill_failed_days INTEGER,
    ADD COLUMN IF NOT EXISTS backfill_last_completed_date DATE,
    ADD COLUMN IF NOT EXISTS last_live_collected_at TIMESTAMPTZ;

ALTER TABLE channels
    ALTER COLUMN source_type SET DEFAULT 'telegram',
    ALTER COLUMN added_at SET DEFAULT NOW(),
    ALTER COLUMN historical_limit_date SET DEFAULT DATE '2026-01-01',
    ALTER COLUMN status SET DEFAULT 'ready',
    ALTER COLUMN validation_status SET DEFAULT 'validated',
    ALTER COLUMN live_enabled SET DEFAULT FALSE,
    ALTER COLUMN backfill_total_days SET DEFAULT 0,
    ALTER COLUMN backfill_completed_days SET DEFAULT 0,
    ALTER COLUMN backfill_failed_days SET DEFAULT 0;

UPDATE channels
SET
    source_type = COALESCE(source_type, 'telegram'),
    input_value = COALESCE(input_value, name),
    telegram_url = COALESCE(
        telegram_url,
        CASE
            WHEN name ~ '^[A-Za-z0-9_]+$' THEN 'https://t.me/' || name
            ELSE NULL
        END
    ),
    added_at = COALESCE(added_at, created_at, NOW()),
    requested_start_date = COALESCE(
        requested_start_date,
        GREATEST(COALESCE(first_message_date::date, DATE '2026-01-01'), DATE '2026-01-01')
    ),
    historical_limit_date = COALESCE(historical_limit_date, DATE '2026-01-01'),
    status = COALESCE(status, 'ready'),
    validation_status = COALESCE(validation_status, 'validated'),
    live_enabled = COALESCE(live_enabled, FALSE),
    backfill_total_days = COALESCE(backfill_total_days, 0),
    backfill_completed_days = COALESCE(backfill_completed_days, 0),
    backfill_failed_days = COALESCE(backfill_failed_days, 0),
    last_live_collected_at = COALESCE(last_live_collected_at, last_collected_at);

ALTER TABLE channels
    ALTER COLUMN source_type SET NOT NULL,
    ALTER COLUMN added_at SET NOT NULL,
    ALTER COLUMN historical_limit_date SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN validation_status SET NOT NULL,
    ALTER COLUMN live_enabled SET NOT NULL,
    ALTER COLUMN backfill_total_days SET NOT NULL,
    ALTER COLUMN backfill_completed_days SET NOT NULL,
    ALTER COLUMN backfill_failed_days SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'channels_source_type_check'
    ) THEN
        ALTER TABLE channels
            ADD CONSTRAINT channels_source_type_check
            CHECK (source_type = 'telegram');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'channels_status_check'
    ) THEN
        ALTER TABLE channels
            ADD CONSTRAINT channels_status_check
            CHECK (status IN (
                'pending_validation',
                'validation_failed',
                'live_enabled',
                'backfilling',
                'ready'
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'channels_validation_status_check'
    ) THEN
        ALTER TABLE channels
            ADD CONSTRAINT channels_validation_status_check
            CHECK (validation_status IN ('pending', 'validated', 'failed'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'channels_requested_start_date_check'
    ) THEN
        ALTER TABLE channels
            ADD CONSTRAINT channels_requested_start_date_check
            CHECK (
                requested_start_date IS NULL
                OR requested_start_date >= historical_limit_date
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'channels_backfill_counts_check'
    ) THEN
        ALTER TABLE channels
            ADD CONSTRAINT channels_backfill_counts_check
            CHECK (
                backfill_total_days >= 0
                AND backfill_completed_days >= 0
                AND backfill_failed_days >= 0
                AND backfill_completed_days + backfill_failed_days <= backfill_total_days
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_channels_name_lower ON channels ((lower(name)));
CREATE UNIQUE INDEX IF NOT EXISTS ux_channels_telegram_channel_id
    ON channels(telegram_channel_id)
    WHERE telegram_channel_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_channels_status ON channels(status);
CREATE INDEX IF NOT EXISTS idx_channels_validation_status ON channels(validation_status);
CREATE INDEX IF NOT EXISTS idx_channels_live_enabled_last_live
    ON channels(live_enabled, last_live_collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_messages_channel_lower ON raw_messages ((lower(channel)));

WITH legacy AS (
    SELECT
        channel AS name,
        min(message_date) AS first_message_date,
        max(message_date) AS last_message_date,
        max(event_timestamp) AS last_collected_at,
        count(*)::INTEGER AS message_count
    FROM raw_messages
    GROUP BY channel
)
INSERT INTO channels (
    name,
    title,
    source_type,
    input_value,
    telegram_url,
    added_at,
    requested_start_date,
    historical_limit_date,
    status,
    validation_status,
    live_enabled,
    backfill_total_days,
    backfill_completed_days,
    backfill_failed_days,
    backfill_last_completed_date,
    last_live_collected_at,
    first_message_date,
    last_message_date,
    last_collected_at,
    message_count
)
SELECT
    legacy.name,
    legacy.name,
    'telegram',
    legacy.name,
    CASE
        WHEN legacy.name ~ '^[A-Za-z0-9_]+$' THEN 'https://t.me/' || legacy.name
        ELSE NULL
    END,
    NOW(),
    GREATEST(legacy.first_message_date::date, DATE '2026-01-01'),
    DATE '2026-01-01',
    'ready',
    'validated',
    FALSE,
    0,
    0,
    0,
    legacy.last_message_date::date,
    legacy.last_collected_at,
    legacy.first_message_date,
    legacy.last_message_date,
    legacy.last_collected_at,
    legacy.message_count
FROM legacy
ON CONFLICT (name) DO UPDATE
SET
    title = COALESCE(channels.title, EXCLUDED.title),
    input_value = COALESCE(channels.input_value, EXCLUDED.input_value),
    telegram_url = COALESCE(channels.telegram_url, EXCLUDED.telegram_url),
    requested_start_date = COALESCE(channels.requested_start_date, EXCLUDED.requested_start_date),
    historical_limit_date = COALESCE(channels.historical_limit_date, EXCLUDED.historical_limit_date),
    backfill_last_completed_date = COALESCE(
        channels.backfill_last_completed_date,
        EXCLUDED.backfill_last_completed_date
    ),
    last_live_collected_at = GREATEST(
        COALESCE(channels.last_live_collected_at, TIMESTAMPTZ 'epoch'),
        COALESCE(EXCLUDED.last_live_collected_at, TIMESTAMPTZ 'epoch')
    ),
    first_message_date = LEAST(
        COALESCE(channels.first_message_date, EXCLUDED.first_message_date),
        COALESCE(EXCLUDED.first_message_date, channels.first_message_date)
    ),
    last_message_date = GREATEST(
        COALESCE(channels.last_message_date, EXCLUDED.last_message_date),
        COALESCE(EXCLUDED.last_message_date, channels.last_message_date)
    ),
    last_collected_at = GREATEST(
        COALESCE(channels.last_collected_at, TIMESTAMPTZ 'epoch'),
        COALESCE(EXCLUDED.last_collected_at, TIMESTAMPTZ 'epoch')
    ),
    message_count = GREATEST(COALESCE(channels.message_count, 0), EXCLUDED.message_count);

-- =====================================================
-- channel_backfill_jobs per-day tracking
-- =====================================================
CREATE TABLE IF NOT EXISTS channel_backfill_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id UUID NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    job_date DATE NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    messages_published INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT channel_backfill_jobs_unique_channel_date UNIQUE (channel_id, job_date),
    CONSTRAINT channel_backfill_jobs_status_check CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'retrying')
    ),
    CONSTRAINT channel_backfill_jobs_attempt_count_check CHECK (attempt_count >= 0),
    CONSTRAINT channel_backfill_jobs_messages_published_check CHECK (messages_published >= 0)
);

CREATE INDEX IF NOT EXISTS idx_channel_backfill_jobs_status_priority
    ON channel_backfill_jobs(status, priority DESC, job_date DESC);
CREATE INDEX IF NOT EXISTS idx_channel_backfill_jobs_channel_date
    ON channel_backfill_jobs(channel_id, job_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_channel_backfill_jobs_single_running
    ON channel_backfill_jobs(channel_id)
    WHERE status = 'running';

DROP TRIGGER IF EXISTS update_channel_backfill_jobs_updated_at ON channel_backfill_jobs;
CREATE TRIGGER update_channel_backfill_jobs_updated_at
    BEFORE UPDATE ON channel_backfill_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DO $$
BEGIN
    RAISE NOTICE 'Migration 004_user_telegram_channels completed successfully';
END $$;
