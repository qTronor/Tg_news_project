#!/bin/bash
# Script: Initialize Neo4j Graph Database
# Description: Apply Cypher initialization script to Neo4j
# Version: 1.0.0
# Date: 2026-01-31

set -euo pipefail

# Configuration
NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"
CYPHER_SCRIPT="neo4j/init.cypher"

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

# Check if cypher-shell is available
if ! command -v cypher-shell &> /dev/null; then
    log_error "cypher-shell not found. Please ensure Neo4j is installed and in PATH."
    log_info "Alternative: Install cypher-shell separately or use Neo4j Browser"
    exit 1
fi

# Check if script exists
if [ ! -f "$CYPHER_SCRIPT" ]; then
    log_error "Cypher script not found: $CYPHER_SCRIPT"
    exit 1
fi

log_info "=========================================="
log_info "Neo4j Initialization Script"
log_info "URI: $NEO4J_URI"
log_info "User: $NEO4J_USER"
log_info "=========================================="

# Test connection
log_info "Testing Neo4j connection..."
if ! cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
    "RETURN 'connected' AS status" > /dev/null 2>&1; then
    log_error "Failed to connect to Neo4j. Please check your credentials and ensure Neo4j is running."
    exit 1
fi
log_info "✓ Neo4j connection successful"

# Apply initialization script
log_info ""
log_info "Applying Neo4j initialization script..."
log_info "Script: $CYPHER_SCRIPT"

cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
    --file "$CYPHER_SCRIPT"

if [ $? -eq 0 ]; then
    log_info "✓ Neo4j initialization completed successfully"
else
    log_error "✗ Failed to initialize Neo4j"
    exit 1
fi

# Verify constraints
log_info ""
log_info "=========================================="
log_info "Verifying Constraints:"
log_info "=========================================="
cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
    "SHOW CONSTRAINTS"

# Verify indexes
log_info ""
log_info "=========================================="
log_info "Verifying Indexes:"
log_info "=========================================="
cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
    "SHOW INDEXES"

# Show database statistics
log_info ""
log_info "=========================================="
log_info "Database Statistics:"
log_info "=========================================="
cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" <<EOF
CALL db.labels() YIELD label
CALL apoc.cypher.run('MATCH (n:' + label + ') RETURN count(n) as count', {})
YIELD value
RETURN label, value.count AS node_count
ORDER BY value.count DESC;
EOF

log_info ""
log_info "=========================================="
log_info "Neo4j initialization completed!"
log_info "=========================================="
log_info ""
log_info "To query the database, run:"
log_info "  cypher-shell -a $NEO4J_URI -u $NEO4J_USER -p <password>"
log_info ""
log_info "Or open Neo4j Browser at:"
log_info "  http://localhost:7474"
