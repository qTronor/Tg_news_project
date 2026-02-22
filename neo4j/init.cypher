// Neo4j Initialization Script
// Description: Create graph schema (constraints, indexes) and helper procedures
// Version: 1.0.0
// Date: 2026-01-31

// =====================================================
// CONSTRAINTS (Uniqueness)
// =====================================================

// Message nodes
CREATE CONSTRAINT message_event_id IF NOT EXISTS
FOR (m:Message) REQUIRE m.event_id IS UNIQUE;

// Entity nodes
CREATE CONSTRAINT entity_id IF NOT EXISTS
FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE;

// Channel nodes
CREATE CONSTRAINT channel_name IF NOT EXISTS
FOR (c:Channel) REQUIRE c.name IS UNIQUE;

// Topic nodes (for topic modeling)
CREATE CONSTRAINT topic_id IF NOT EXISTS
FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE;

// =====================================================
// INDEXES (Performance)
// =====================================================

// Message indexes
CREATE INDEX message_timestamp IF NOT EXISTS
FOR (m:Message) ON (m.timestamp);

CREATE INDEX message_channel IF NOT EXISTS
FOR (m:Message) ON (m.channel);

CREATE INDEX message_sentiment IF NOT EXISTS
FOR (m:Message) ON (m.sentiment_label);

CREATE INDEX message_views IF NOT EXISTS
FOR (m:Message) ON (m.views);

CREATE INDEX message_channel_timestamp IF NOT EXISTS
FOR (m:Message) ON (m.channel, m.timestamp);

// Entity indexes
CREATE INDEX entity_type IF NOT EXISTS
FOR (e:Entity) ON (e.entity_type);

CREATE INDEX entity_normalized_name IF NOT EXISTS
FOR (e:Entity) ON (e.normalized_name);

CREATE INDEX entity_mention_count IF NOT EXISTS
FOR (e:Entity) ON (e.mention_count);

CREATE INDEX entity_wikidata IF NOT EXISTS
FOR (e:Entity) ON (e.wikidata_id);

CREATE INDEX entity_type_name IF NOT EXISTS
FOR (e:Entity) ON (e.entity_type, e.normalized_name);

// Channel indexes
CREATE INDEX channel_subscriber_count IF NOT EXISTS
FOR (c:Channel) ON (c.subscriber_count);

CREATE INDEX channel_message_count IF NOT EXISTS
FOR (c:Channel) ON (c.message_count);

// Topic indexes
CREATE INDEX topic_label IF NOT EXISTS
FOR (t:Topic) ON (t.label);

// Full-text search indexes (Neo4j 4.x+)
CREATE FULLTEXT INDEX message_text_fulltext IF NOT EXISTS
FOR (m:Message) ON EACH [m.text, m.cleaned_text];

CREATE FULLTEXT INDEX entity_name_fulltext IF NOT EXISTS
FOR (e:Entity) ON EACH [e.normalized_name, e.original_text];

// =====================================================
// HELPER PROCEDURES
// =====================================================
// NOTE:
// We intentionally do NOT create APOC custom procedures here.
// The official "apoc" plugin installed by Neo4j in Docker is the APOC core jar,
// which doesn't ship `apoc.custom.asProcedure`.
// Our writer service will use plain Cypher `MERGE` statements instead.

// =====================================================
// SEED DATA (Optional: Create initial channel nodes)
// =====================================================

// Create channel nodes for common channels
MERGE (c:Channel {name: 'rbc_news'})
ON CREATE SET
  c.title = 'РБК Новости',
  c.description = 'Официальный канал РБК',
  c.created_at = datetime();

MERGE (c:Channel {name: 'cbpub'})
ON CREATE SET
  c.title = 'ЦБ РФ',
  c.description = 'Официальный канал Центрального Банка России',
  c.created_at = datetime();

// =====================================================
// UTILITY QUERIES
// =====================================================

// Query: Get database statistics
// CALL db.labels() YIELD label
// CALL apoc.cypher.run('MATCH (n:' + label + ') RETURN count(n) as count', {})
// YIELD value
// RETURN label, value.count;

// Query: Check constraint status
// SHOW CONSTRAINTS;

// Query: Check index status
// SHOW INDEXES;

// =====================================================
// SAMPLE QUERIES (for testing)
// =====================================================

// 1. Top 10 most mentioned entities
// MATCH (e:Entity)
// RETURN e.normalized_name, e.entity_type, e.mention_count
// ORDER BY e.mention_count DESC
// LIMIT 10;

// 2. Recent messages with sentiment
// MATCH (m:Message)
// WHERE m.timestamp >= datetime() - duration('P7D')
// RETURN m.channel, m.text, m.sentiment_label, m.sentiment_score
// ORDER BY m.timestamp DESC
// LIMIT 20;

// 3. Entity co-occurrence network
// MATCH (e1:Entity)<-[:MENTIONS]-(m:Message)-[:MENTIONS]->(e2:Entity)
// WHERE e1.entity_id < e2.entity_id
// WITH e1, e2, count(m) as co_occurrence_count
// WHERE co_occurrence_count >= 3
// RETURN e1.normalized_name, e2.normalized_name, co_occurrence_count
// ORDER BY co_occurrence_count DESC
// LIMIT 50;

// =====================================================
// CLEANUP PROCEDURES (for maintenance)
// =====================================================

// Delete old messages (retention policy: 90 days)
// MATCH (m:Message)
// WHERE m.timestamp < datetime() - duration('P90D')
// DETACH DELETE m;

// Recalculate entity statistics
// MATCH (e:Entity)<-[r:MENTIONS]-(m:Message)
// WITH e, count(r) as mention_count, avg(m.sentiment_score) as avg_sentiment
// SET e.mention_count = mention_count,
//     e.avg_sentiment = avg_sentiment;

// =====================================================
// COMPLETION MESSAGE
// =====================================================

RETURN 'Neo4j initialization completed successfully' AS status,
       'Constraints: 4, Indexes: 15+' AS summary,
       datetime() AS completed_at;
