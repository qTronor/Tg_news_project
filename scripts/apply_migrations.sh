#!/bin/bash
# Script: Apply Postgres Database Migrations
# Description: Execute SQL migration scripts for Telegram News Pipeline
# Version: 1.0.0
# Date: 2026-01-31

set -euo pipefail

# Configuration
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-telegram_news}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-}"

MIGRATIONS_DIR="migrations"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if psql is available
if ! command -v psql &> /dev/null; then
    log_error "psql not found. Please ensure PostgreSQL client is installed."
    exit 1
fi

# Check if migrations directory exists
if [ ! -d "$MIGRATIONS_DIR" ]; then
    log_error "Migrations directory not found: $MIGRATIONS_DIR"
    exit 1
fi

# Build connection string
if [ -n "$DB_PASSWORD" ]; then
    export PGPASSWORD="$DB_PASSWORD"
fi

PSQL_CMD="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME"

log_info "=========================================="
log_info "Database Migration Script"
log_info "Host: $DB_HOST:$DB_PORT"
log_info "Database: $DB_NAME"
log_info "User: $DB_USER"
log_info "=========================================="

# Test database connection
log_info "Testing database connection..."
if ! $PSQL_CMD -c "SELECT version();" > /dev/null 2>&1; then
    log_error "Failed to connect to database. Please check your credentials."
    exit 1
fi
log_info "✓ Database connection successful"

# Create migrations tracking table if not exists
log_info "Creating migrations tracking table..."
$PSQL_CMD <<EOF
CREATE TABLE IF NOT EXISTS schema_migrations (
    id SERIAL PRIMARY KEY,
    version VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    checksum VARCHAR(64)
);
EOF

# Function to get checksum of a file
get_checksum() {
    local file=$1
    if command -v sha256sum &> /dev/null; then
        sha256sum "$file" | awk '{print $1}'
    elif command -v shasum &> /dev/null; then
        shasum -a 256 "$file" | awk '{print $1}'
    else
        echo "unknown"
    fi
}

# Function to check if migration is already applied
is_migration_applied() {
    local version=$1
    local count=$($PSQL_CMD -t -c "SELECT COUNT(*) FROM schema_migrations WHERE version = '$version';")
    [ "$count" -gt 0 ]
}

# Function to apply a migration
apply_migration() {
    local file=$1
    local version=$(basename "$file" | sed 's/\.sql$//')
    local name=$(head -n 2 "$file" | grep "Description:" | sed 's/.*Description: //')
    local checksum=$(get_checksum "$file")
    
    if is_migration_applied "$version"; then
        log_warn "Migration $version already applied. Skipping..."
        return 0
    fi
    
    log_info "Applying migration: $version"
    log_info "  File: $file"
    log_info "  Description: $name"
    
    # Execute migration in a transaction
    $PSQL_CMD <<EOF
BEGIN;

-- Execute migration file
\i $file

-- Record migration
INSERT INTO schema_migrations (version, name, checksum)
VALUES ('$version', '$name', '$checksum');

COMMIT;
EOF
    
    if [ $? -eq 0 ]; then
        log_info "✓ Migration $version applied successfully"
    else
        log_error "✗ Failed to apply migration $version"
        return 1
    fi
}

# Apply all migrations in order
log_info ""
log_info "Applying migrations..."

for migration_file in $(ls -1 $MIGRATIONS_DIR/*.sql | sort); do
    apply_migration "$migration_file"
done

# Show applied migrations
log_info ""
log_info "=========================================="
log_info "Applied Migrations:"
log_info "=========================================="
$PSQL_CMD -c "SELECT version, name, applied_at FROM schema_migrations ORDER BY applied_at;"

# Show table statistics
log_info ""
log_info "=========================================="
log_info "Database Statistics:"
log_info "=========================================="
$PSQL_CMD <<EOF
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
EOF

log_info ""
log_info "=========================================="
log_info "Migration completed successfully!"
log_info "=========================================="

# Cleanup
unset PGPASSWORD
