# Graph Builder Design Note

## Status

Graph builder is **deferred** — not a separate service yet. This document pins the contract
so future implementation can key on `canonical_id` from day one.

## Contract: `ner.enriched` → Graph

As of migration 017 + ner_extractor provider chain, each entity in a `ner.enriched` event carries:

```json
{
  "text": "Путин",
  "type": "PERSON",
  "start": 0,
  "end": 5,
  "confidence": 1.0,
  "normalized": "путин",
  "canonical_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "canonical_name": "Владимир Путин",
  "aliases": ["Путин", "В. Путин", "Владимир Путин"],
  "wikidata_id": null
}
```

`canonical_id` is `null` when `enable_canonical_resolution=false`.

## Neo4j Entity Node Contract

When `graph_builder` service is implemented, entity nodes must follow:

```cypher
MERGE (e:Entity {entity_id: $canonical_id})
ON CREATE SET
  e.name          = $canonical_name,
  e.type          = $entity_type,
  e.aliases       = $aliases,
  e.wikidata_id   = $wikidata_id,
  e.first_seen_at = datetime(),
  e.mention_count = 1
ON MATCH SET
  e.last_seen_at  = datetime(),
  e.mention_count = e.mention_count + 1,
  e.aliases       = $aliases
```

Key invariants:
- **Constraint**: `CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE`
  (already in `neo4j/init.cypher`)
- **Key**: always `canonical_id` — never surface text. Surface form goes in `aliases`.
- **Aliases**: stored as a list property, not separate nodes. Each ner.enriched event may carry
  updated aliases; overwrite the list on MATCH.
- **Deduplication**: two mentions of "Путин" and "Владимир Путин" with same `canonical_id`
  → one Entity node with `mention_count = 2`.

## `CO_OCCURS_WITH` Relationship

```cypher
MATCH (a:Entity {entity_id: $canonical_id_a}), (b:Entity {entity_id: $canonical_id_b})
MERGE (a)-[r:CO_OCCURS_WITH]-(b)
ON CREATE SET r.count = 1, r.first_seen_at = datetime()
ON MATCH SET  r.count = r.count + 1, r.last_seen_at = datetime()
```

Direction: undirected (use unordered pair to avoid duplicates).

## Downstream: `graph.updates` topic

After MERGE, publish to `graph.updates` per `schemas/graph_update.schema.json`:

```json
{
  "event_type": "graph_entity_upserted",
  "canonical_id": "...",
  "canonical_name": "Владимир Путин",
  "entity_type": "PERSON",
  "source_event_id": "channel:12345"
}
```

## Rollout Order

1. ✅ `ner.enriched` events carry `canonical_id` (this PR)
2. 🔲 Create `graph_builder/` service consuming `ner.enriched`
3. 🔲 Add `CREATE CONSTRAINT` guard in `neo4j/init.cypher` (already present)
4. 🔲 Migrate existing Neo4j nodes: run `MATCH (e:Entity) SET e.entity_id = e.id` if needed
