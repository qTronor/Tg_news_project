#!/bin/bash
# Script: Validate JSON Schema Files
# Description: Validate all JSON schema files for correctness
# Version: 1.0.0
# Date: 2026-01-31

set -euo pipefail

SCHEMAS_DIR="schemas"

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

# Check if jq is available
if ! command -v jq &> /dev/null; then
    log_error "jq not found. Please install jq to validate JSON schemas."
    exit 1
fi

# Check if schemas directory exists
if [ ! -d "$SCHEMAS_DIR" ]; then
    log_error "Schemas directory not found: $SCHEMAS_DIR"
    exit 1
fi

log_info "=========================================="
log_info "JSON Schema Validation"
log_info "Directory: $SCHEMAS_DIR"
log_info "=========================================="

errors=0
total=0

# Validate each schema file
for schema_file in $(ls -1 $SCHEMAS_DIR/*.json); do
    total=$((total + 1))
    schema_name=$(basename "$schema_file")
    
    log_info "Validating: $schema_name"
    
    # Check if file is valid JSON
    if ! jq empty "$schema_file" 2>/dev/null; then
        log_error "✗ Invalid JSON in $schema_name"
        errors=$((errors + 1))
        continue
    fi
    
    # Check required JSON Schema fields
    if ! jq -e '."$schema"' "$schema_file" > /dev/null 2>&1; then
        log_warn "  Missing \$schema field in $schema_name"
    fi
    
    if ! jq -e '.title' "$schema_file" > /dev/null 2>&1; then
        log_warn "  Missing title field in $schema_name"
    fi
    
    if ! jq -e '.type' "$schema_file" > /dev/null 2>&1; then
        log_warn "  Missing type field in $schema_name"
    fi
    
    # Extract some statistics
    required_count=$(jq -r '.required | length // 0' "$schema_file")
    properties_count=$(jq -r '.properties | length // 0' "$schema_file")
    
    log_info "  ✓ Valid JSON"
    log_info "    Required fields: $required_count"
    log_info "    Properties: $properties_count"
done

log_info ""
log_info "=========================================="
if [ $errors -eq 0 ]; then
    log_info "✓ All $total schemas are valid!"
else
    log_error "✗ $errors out of $total schemas have errors"
    exit 1
fi
log_info "=========================================="
