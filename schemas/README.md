# JSON Schemas for Telegram News Pipeline

This directory contains JSON Schema definitions for all event types in the data pipeline.

## Overview

All schemas follow JSON Schema Draft 07 specification and define the structure and validation rules for events flowing through Kafka topics.

## Schema Files

### Main Pipeline Events

| Schema File | Event Type | Description |
|------------|------------|-------------|
| `raw_message.schema.json` | `raw_message` | Raw messages from Telegram |
| `persisted_message.schema.json` | `persisted` | Persistence confirmation |
| `preprocessed_message.schema.json` | `preprocessed` | Cleaned and tokenized text |
| `sentiment_enriched.schema.json` | `sentiment_enriched` | Sentiment analysis results |
| `ner_enriched.schema.json` | `ner_enriched` | Named entities and relations |
| `graph_update.schema.json` | `graph_update` | Neo4j update commands |

## Common Structure

All events share a common metadata structure:

```json
{
  "event_id": "string (format: {channel}:{message_id})",
  "event_type": "enum [raw_message, persisted, ...]",
  "event_timestamp": "string (ISO 8601 UTC)",
  "event_version": "string (semver)",
  "source_system": "string (producer service name)",
  "trace_id": "string (UUID for distributed tracing)",
  "payload": { ... }
}
```

## Validation

### Using Python

```python
import json
from jsonschema import validate, ValidationError

# Load schema
with open('schemas/raw_message.schema.json') as f:
    schema = json.load(f)

# Load event
event = {
    "event_id": "rbc_news:123456",
    "event_type": "raw_message",
    # ... rest of event
}

# Validate
try:
    validate(instance=event, schema=schema)
    print("✓ Event is valid")
except ValidationError as e:
    print(f"✗ Validation error: {e.message}")
```

### Using Node.js

```javascript
const Ajv = require('ajv');
const ajv = new Ajv();

const schema = require('./schemas/raw_message.schema.json');
const validate = ajv.compile(schema);

const event = {
  event_id: 'rbc_news:123456',
  event_type: 'raw_message',
  // ... rest of event
};

const valid = validate(event);
if (!valid) {
  console.log('✗ Validation errors:', validate.errors);
} else {
  console.log('✓ Event is valid');
}
```

### Using CLI (ajv-cli)

```bash
# Install ajv-cli
npm install -g ajv-cli

# Validate an event
ajv validate -s schemas/raw_message.schema.json -d event.json
```

### Using Our Script

```bash
# Validate all schemas
./scripts/validate_schemas.sh
```

## Schema Versioning

Schemas follow semantic versioning:

- **Major version** (v2.0.0): Breaking changes (remove fields, change types)
- **Minor version** (v1.1.0): Backward-compatible additions (new optional fields)
- **Patch version** (v1.0.1): Documentation or non-functional changes

### Breaking Change Process

1. Create new schema file: `raw_message.schema.v2.json`
2. Create new Kafka topic: `raw.telegram.messages.v2`
3. Deploy dual-write producer (writes to both v1 and v2)
4. Migrate consumers to v2
5. Deprecate v1 (after grace period)

## Entity Types (NER)

Standard entity types used in `ner_enriched.schema.json`:

| Type | Description | Example |
|------|-------------|---------|
| `PERSON` | Person names | "Владимир Путин" |
| `ORG` | Organizations | "Центробанк" |
| `GPE` | Geopolitical entities | "Россия", "Москва" |
| `LOC` | Non-GPE locations | "Красная площадь" |
| `PRODUCT` | Products/brands | "iPhone" |
| `EVENT` | Named events | "Олимпиада 2024" |
| `DATE` | Dates | "31 января 2026" |
| `TIME` | Times | "14:30" |
| `MONEY` | Monetary values | "1000 рублей" |
| `PERCENT` | Percentages | "18%" |
| `QUANTITY` | Quantities | "5 кг" |
| `ORDINAL` | Ordinal numbers | "первый" |
| `CARDINAL` | Cardinal numbers | "123" |

## Sentiment Labels

Standard sentiment labels in `sentiment_enriched.schema.json`:

- `positive`: Positive sentiment (score > 0.6)
- `negative`: Negative sentiment (score < 0.4)
- `neutral`: Neutral sentiment (0.4 ≤ score ≤ 0.6)

## Graph Operations

Graph update operations in `graph_update.schema.json`:

| Operation | Description |
|-----------|-------------|
| `CREATE` | Create new node/relationship (fails if exists) |
| `MERGE` | Create if not exists, otherwise update |
| `UPDATE` | Update existing node/relationship |
| `DELETE` | Delete node/relationship |

## Examples

See `examples/` directory for sample events for each schema:

```bash
examples/
├── raw_message.example.json
├── persisted_message.example.json
├── preprocessed_message.example.json
├── sentiment_enriched.example.json
├── ner_enriched.example.json
└── graph_update.example.json
```

## Integration with Kafka

### Producer

```python
from kafka import KafkaProducer
import json

producer = KafkaProducer(
    bootstrap_servers=['localhost:9092'],
    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    key_serializer=lambda k: k.encode('utf-8')
)

event = {
    "event_id": "rbc_news:123456",
    "event_type": "raw_message",
    # ... rest of event
}

# Key is event_id for ordering and deduplication
producer.send(
    topic='raw.telegram.messages',
    key=event['event_id'],
    value=event
)
```

### Consumer

```python
from kafka import KafkaConsumer
import json

consumer = KafkaConsumer(
    'raw.telegram.messages',
    bootstrap_servers=['localhost:9092'],
    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
    key_deserializer=lambda k: k.decode('utf-8'),
    auto_offset_reset='earliest',
    enable_auto_commit=False,
    group_id='my-consumer-group'
)

for message in consumer:
    event = message.value
    # Validate against schema
    # Process event
    # Commit offset
    consumer.commit()
```

## References

- [JSON Schema Specification](https://json-schema.org/)
- [Understanding JSON Schema](https://json-schema.org/understanding-json-schema/)
- [AJV (Another JSON Validator)](https://ajv.js.org/)
- [jsonschema (Python)](https://python-jsonschema.readthedocs.io/)
