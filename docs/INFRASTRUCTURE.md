# Infrastructure Setup Guide

Quick start guide for setting up the complete Telegram News Pipeline infrastructure.

## Prerequisites

### Required Software

- Docker & Docker Compose
- PostgreSQL 15+
- Neo4j 5.x
- Apache Kafka 3.x
- Python 3.11+

### Optional Tools

- `jq` - JSON processing (for schema validation)
- `kafka-topics.sh` - Kafka CLI tools
- `psql` - PostgreSQL client
- `cypher-shell` - Neo4j client

## Quick Start

### 1. Clone Repository

```bash
git clone <repo-url>
cd Tg_news_project
```

### 2. Make Scripts Executable

```bash
chmod +x scripts/*.sh
```

### 3. Set Environment Variables

Create `.env` file in project root:

```bash
# Telegram API
export TG_API_ID="123456"
export TG_API_HASH="your_hash_here"
export TG_STRING_SESSION="your_session_string"

# PostgreSQL
export DB_HOST="localhost"
export DB_PORT="5432"
export DB_NAME="telegram_news"
export DB_USER="postgres"
export DB_PASSWORD="your_password"

# Neo4j
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your_password"

# Kafka
export KAFKA_BOOTSTRAP_SERVER="localhost:9092"
export REPLICATION_FACTOR="3"
```

Load environment variables:

```bash
source .env
```

### 4. Initialize Databases

#### PostgreSQL

```bash
# Create database
createdb telegram_news

# Apply migrations
./scripts/apply_migrations.sh
```

#### Neo4j

```bash
# Ensure Neo4j is running
docker-compose up -d neo4j

# Initialize graph schema
./scripts/init_neo4j.sh
```

### 5. Create Kafka Topics

```bash
# Ensure Kafka is running
docker-compose up -d kafka zookeeper

# Create all topics
./scripts/create_kafka_topics.sh
```

### 6. Validate Schemas

```bash
./scripts/validate_schemas.sh
```

## Docker Compose Setup

### Full Stack

Create `docker-compose.infrastructure.yml`:

```yaml
version: '3.8'

services:
  # PostgreSQL
  postgres:
    image: postgres:15-alpine
    container_name: telegram-news-postgres
    environment:
      POSTGRES_DB: telegram_news
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./migrations:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Neo4j
  neo4j:
    image: neo4j:5-community
    container_name: telegram-news-neo4j
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}
      NEO4J_dbms_memory_heap_max__size: 2G
      NEO4J_dbms_memory_pagecache_size: 1G
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
    ports:
      - "7474:7474"  # HTTP
      - "7687:7687"  # Bolt
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
      - ./neo4j:/var/lib/neo4j/import
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "neo4j", "-p", "${NEO4J_PASSWORD}", "RETURN 1"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Zookeeper
  zookeeper:
    image: confluentinc/cp-zookeeper:7.5.0
    container_name: telegram-news-zookeeper
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    ports:
      - "2181:2181"
    volumes:
      - zookeeper_data:/var/lib/zookeeper/data
      - zookeeper_logs:/var/lib/zookeeper/log

  # Kafka
  kafka:
    image: confluentinc/cp-kafka:7.5.0
    container_name: telegram-news-kafka
    depends_on:
      - zookeeper
    ports:
      - "9092:9092"
      - "9093:9093"
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092,PLAINTEXT_INTERNAL://kafka:9093
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_INTERNAL:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT_INTERNAL
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"
    volumes:
      - kafka_data:/var/lib/kafka/data
    healthcheck:
      test: ["CMD", "kafka-broker-api-versions", "--bootstrap-server", "localhost:9092"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Kafka UI (optional, for monitoring)
  kafka-ui:
    image: provectuslabs/kafka-ui:latest
    container_name: telegram-news-kafka-ui
    depends_on:
      - kafka
    ports:
      - "8080:8080"
    environment:
      KAFKA_CLUSTERS_0_NAME: local
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka:9093
      KAFKA_CLUSTERS_0_ZOOKEEPER: zookeeper:2181

  # Redis (for caching and deduplication)
  redis:
    image: redis:7-alpine
    container_name: telegram-news-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
  neo4j_data:
  neo4j_logs:
  zookeeper_data:
  zookeeper_logs:
  kafka_data:
  redis_data:
```

Start all services:

```bash
docker-compose -f docker-compose.infrastructure.yml up -d
```

## Verification

### Check Services Status

```bash
# PostgreSQL
psql -h localhost -U postgres -d telegram_news -c "SELECT version();"

# Neo4j
cypher-shell -a bolt://localhost:7687 -u neo4j -p ${NEO4J_PASSWORD} "RETURN 'OK' AS status"

# Kafka
kafka-topics.sh --bootstrap-server localhost:9092 --list

# Redis
redis-cli ping
```

### Check Database Schema

```bash
# PostgreSQL tables
psql -h localhost -U postgres -d telegram_news -c "\dt"

# Neo4j constraints
cypher-shell -a bolt://localhost:7687 -u neo4j -p ${NEO4J_PASSWORD} "SHOW CONSTRAINTS"
```

### Check Kafka Topics

```bash
# List all topics
kafka-topics.sh --bootstrap-server localhost:9092 --list

# Describe a specific topic
kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic raw.telegram.messages
```

## Monitoring

### Access Web UIs

- **Neo4j Browser**: http://localhost:7474
- **Kafka UI**: http://localhost:8080

### Check Logs

```bash
# PostgreSQL
docker logs telegram-news-postgres

# Neo4j
docker logs telegram-news-neo4j

# Kafka
docker logs telegram-news-kafka
```

## Maintenance

### Clean Up Old Data

```bash
# PostgreSQL: Clean processed_events and outbox
psql -h localhost -U postgres -d telegram_news <<EOF
SELECT cleanup_processed_events();
SELECT cleanup_outbox();
EOF

# Neo4j: Remove old messages (90+ days)
cypher-shell -a bolt://localhost:7687 -u neo4j -p ${NEO4J_PASSWORD} <<EOF
MATCH (m:Message)
WHERE m.timestamp < datetime() - duration('P90D')
DETACH DELETE m;
EOF
```

### Backup

```bash
# PostgreSQL
pg_dump -h localhost -U postgres telegram_news > backup.sql

# Neo4j
docker exec telegram-news-neo4j neo4j-admin database dump neo4j --to=/backups/neo4j-backup.dump
```

## Troubleshooting

### Kafka Connection Issues

```bash
# Check if Kafka is listening
nc -zv localhost 9092

# Check consumer lag
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group <group-name>
```

### PostgreSQL Connection Issues

```bash
# Check if PostgreSQL is running
pg_isready -h localhost -p 5432

# Check active connections
psql -h localhost -U postgres -c "SELECT * FROM pg_stat_activity;"
```

### Neo4j Connection Issues

```bash
# Check if Neo4j is running
curl http://localhost:7474

# Check database status
cypher-shell -a bolt://localhost:7687 -u neo4j -p ${NEO4J_PASSWORD} "CALL dbms.components()"
```

## Next Steps

1. Deploy services (see individual service READMEs)
2. Configure monitoring (Prometheus + Grafana)
3. Set up alerting
4. Configure backup automation

## References

- [Main Contracts Documentation](docs/contracts.md)
- [Engineering Standards](docs/engineering-standards.md)
- [Schema Documentation](schemas/README.md)
