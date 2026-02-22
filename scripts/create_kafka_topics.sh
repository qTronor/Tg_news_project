#!/bin/bash
# Script: Create Kafka Topics for Telegram News Pipeline
# Description: Automated topic creation based on contracts
# Version: 1.0.0
# Date: 2026-01-31

set -euo pipefail

# Configuration
KAFKA_BOOTSTRAP_SERVER="${KAFKA_BOOTSTRAP_SERVER:-localhost:9092}"
REPLICATION_FACTOR="${REPLICATION_FACTOR:-3}"
MIN_INSYNC_REPLICAS="${MIN_INSYNC_REPLICAS:-2}"

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

# Check if kafka-topics.sh is available
if ! command -v kafka-topics.sh &> /dev/null; then
    log_error "kafka-topics.sh not found. Please ensure Kafka is installed and in PATH."
    exit 1
fi

# Function to create a topic
create_topic() {
    local name=$1
    local partitions=$2
    local retention_ms=$3
    local description=$4
    
    log_info "Creating topic: $name"
    log_info "  Partitions: $partitions"
    log_info "  Retention: ${retention_ms}ms ($(($retention_ms / 86400000)) days)"
    log_info "  Description: $description"
    
    if kafka-topics.sh --bootstrap-server "$KAFKA_BOOTSTRAP_SERVER" \
        --list | grep -q "^${name}$"; then
        log_warn "Topic $name already exists. Skipping..."
        return 0
    fi
    
    kafka-topics.sh --bootstrap-server "$KAFKA_BOOTSTRAP_SERVER" \
        --create \
        --topic "$name" \
        --partitions "$partitions" \
        --replication-factor "$REPLICATION_FACTOR" \
        --config retention.ms="$retention_ms" \
        --config compression.type=lz4 \
        --config min.insync.replicas="$MIN_INSYNC_REPLICAS" \
        --config cleanup.policy=delete \
        --config max.message.bytes=10485760 \
        --config segment.ms=86400000
    
    if [ $? -eq 0 ]; then
        log_info "✓ Topic $name created successfully"
    else
        log_error "✗ Failed to create topic $name"
        return 1
    fi
}

log_info "=========================================="
log_info "Kafka Topics Creation Script"
log_info "Bootstrap Server: $KAFKA_BOOTSTRAP_SERVER"
log_info "Replication Factor: $REPLICATION_FACTOR"
log_info "=========================================="

# Main Pipeline Topics
log_info ""
log_info "Creating main pipeline topics..."

create_topic "raw.telegram.messages" 6 2592000000 \
    "Raw messages collected from Telegram channels"

create_topic "persisted.messages" 6 604800000 \
    "Confirmation that messages were persisted to Postgres"

create_topic "preprocessed.messages" 6 2592000000 \
    "Messages after text preprocessing"

create_topic "sentiment.enriched" 6 2592000000 \
    "Messages enriched with sentiment analysis"

create_topic "ner.enriched" 6 2592000000 \
    "Messages enriched with named entity recognition"

create_topic "graph.updates" 6 604800000 \
    "Graph update commands for Neo4j"

# Dead Letter Queue Topics
log_info ""
log_info "Creating DLQ topics..."

create_topic "dlq.raw.messages" 3 7776000000 \
    "Failed raw message processing"

create_topic "dlq.preprocessing" 3 7776000000 \
    "Failed preprocessing operations"

create_topic "dlq.sentiment" 3 7776000000 \
    "Failed sentiment analysis"

create_topic "dlq.ner" 3 7776000000 \
    "Failed NER extraction"

create_topic "dlq.graph" 3 7776000000 \
    "Failed graph updates"

# Verify all topics
log_info ""
log_info "=========================================="
log_info "Verifying topics..."
log_info "=========================================="

kafka-topics.sh --bootstrap-server "$KAFKA_BOOTSTRAP_SERVER" --list

log_info ""
log_info "=========================================="
log_info "Topic creation completed!"
log_info "=========================================="
log_info ""
log_info "To describe a topic, run:"
log_info "  kafka-topics.sh --bootstrap-server $KAFKA_BOOTSTRAP_SERVER --describe --topic <topic-name>"
log_info ""
log_info "To view messages in a topic, run:"
log_info "  kafka-console-consumer.sh --bootstrap-server $KAFKA_BOOTSTRAP_SERVER --topic <topic-name> --from-beginning"
