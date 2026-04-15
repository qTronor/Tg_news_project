-- Migration: 002_auth_schema
-- Description: Create auth database and tables for user management (separate from analytics)
-- Date: 2026-03-05

-- =====================================================
-- Create separate auth database within the same PG instance
-- =====================================================
-- NOTE: docker-entrypoint-initdb.d scripts run against the default DB (telegram_news).
-- We create tg_news_auth as a separate database for PII isolation.

SELECT 'CREATE DATABASE tg_news_auth'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'tg_news_auth')\gexec

-- Connect to the new database and set it up
\connect tg_news_auth

-- Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- TABLE: users
-- =====================================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);
CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);
CREATE INDEX IF NOT EXISTS ix_users_role ON users(role);

COMMENT ON TABLE users IS 'User accounts. PII — stored separately from analytics data.';
COMMENT ON COLUMN users.password_hash IS 'bcrypt hash (12 rounds). Never store plaintext.';

-- =====================================================
-- TABLE: refresh_sessions
-- =====================================================
CREATE TABLE IF NOT EXISTS refresh_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_agent TEXT,
    ip_address INET
);

CREATE INDEX IF NOT EXISTS ix_refresh_sessions_user_id ON refresh_sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_refresh_sessions_expires ON refresh_sessions(expires_at);

COMMENT ON TABLE refresh_sessions IS 'Refresh tokens (SHA-256 hashed). Rotated on each refresh.';

-- =====================================================
-- TABLE: admin_audit_log
-- =====================================================
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(50),
    target_id VARCHAR(255),
    old_value JSONB,
    new_value JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_audit_admin_created ON admin_audit_log(admin_id, created_at);
CREATE INDEX IF NOT EXISTS ix_audit_action ON admin_audit_log(action);
CREATE INDEX IF NOT EXISTS ix_audit_created ON admin_audit_log(created_at DESC);

COMMENT ON TABLE admin_audit_log IS 'Immutable audit trail of all admin actions. Retention: per policy.';

-- =====================================================
-- TABLE: message_reactions
-- =====================================================
CREATE TABLE IF NOT EXISTS message_reactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_event_id VARCHAR(255) NOT NULL,
    reaction VARCHAR(10) NOT NULL CHECK (reaction IN ('like', 'dislike')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, message_event_id)
);

CREATE INDEX IF NOT EXISTS ix_reactions_message ON message_reactions(message_event_id);
CREATE INDEX IF NOT EXISTS ix_reactions_user ON message_reactions(user_id);

COMMENT ON TABLE message_reactions IS 'User reactions (like/dislike) on messages. References event_id from analytics DB.';

-- =====================================================
-- TABLE: channel_visibility
-- =====================================================
CREATE TABLE IF NOT EXISTS channel_visibility (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_name VARCHAR(255) UNIQUE NOT NULL,
    is_visible BOOLEAN NOT NULL DEFAULT true,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_channel_visibility_name ON channel_visibility(channel_name);

COMMENT ON TABLE channel_visibility IS 'Admin-managed channel visibility for all users.';

-- =====================================================
-- SECURITY: Least privilege
-- =====================================================
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'auth_readonly') THEN
    CREATE ROLE auth_readonly NOLOGIN;
  END IF;
END $$;

GRANT CONNECT ON DATABASE tg_news_auth TO auth_readonly;
GRANT USAGE ON SCHEMA public TO auth_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO auth_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO auth_readonly;

-- =====================================================
-- TRIGGERS
-- =====================================================
CREATE OR REPLACE FUNCTION auth_update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION auth_update_updated_at();

CREATE TRIGGER update_channel_visibility_updated_at
    BEFORE UPDATE ON channel_visibility
    FOR EACH ROW
    EXECUTE FUNCTION auth_update_updated_at();

-- =====================================================
-- MAINTENANCE: Cleanup expired sessions
-- =====================================================
CREATE OR REPLACE FUNCTION cleanup_expired_sessions()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM refresh_sessions
    WHERE expires_at < NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_expired_sessions() IS 'Remove expired refresh sessions. Run periodically.';

-- =====================================================
-- COMPLETION
-- =====================================================
DO $$
BEGIN
    RAISE NOTICE 'Migration 002_auth_schema completed successfully';
    RAISE NOTICE 'Auth tables created: %', (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public');
END $$;
