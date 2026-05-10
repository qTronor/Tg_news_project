#!/usr/bin/env python3
"""
End-to-end test of multilingual ML pipeline.
Tests sentiment analysis and NER extraction for RU and EN messages.
"""

import json
import time
import sys
from datetime import datetime
from confluent_kafka import Producer, Consumer, KafkaError
import psycopg2
from psycopg2.extras import RealDictCursor

# ===== Config =====
KAFKA_BOOTSTRAP = "localhost:9092"
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "telegram_news",
    "user": "postgres",
    "password": "postgres"
}

# Test messages
TEST_MESSAGES = [
    {
        "id": "test_ru_001",
        "text": "Президент России провел встречу с премьер-министром Великобритании. Обсуждались вопросы торговли и безопасности.",
        "source": "test",
        "language": "ru",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    },
    {
        "id": "test_en_001",
        "text": "The President of the United States met with the UK Prime Minister. They discussed trade agreements and security matters.",
        "source": "test",
        "language": "en",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    },
    {
        "id": "test_ru_sentiment_pos",
        "text": "Это отличное решение! Я очень доволен результатами и рекомендую это всем своим друзьям.",
        "source": "test",
        "language": "ru",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    },
    {
        "id": "test_en_sentiment_pos",
        "text": "I'm absolutely thrilled with this product! It exceeded all my expectations and I'm very happy.",
        "source": "test",
        "language": "en",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    },
]

def send_test_messages():
    """Send test messages to Kafka."""
    print("\n📤 Sending test messages to Kafka...")
    producer = Producer({
        'bootstrap.servers': KAFKA_BOOTSTRAP,
        'client.id': 'test-producer'
    })

    for msg in TEST_MESSAGES:
        try:
            producer.produce(
                'raw.messages',
                key=msg["id"].encode('utf-8'),
                value=json.dumps(msg).encode('utf-8')
            )
            print(f"  ✓ {msg['id']} ({msg['language']}) - {msg['text'][:50]}...")
        except Exception as e:
            print(f"  ✗ Failed to send {msg['id']}: {e}")
            return False

    producer.flush()
    print("  ✓ All messages sent successfully")
    return True

def check_sentiment_results():
    """Check sentiment analysis results in database."""
    print("\n📊 Checking sentiment analysis results...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT
                message_id,
                language,
                sentiment,
                model_language,
                emotion_model_name,
                aspects_status,
                (emotions->>'anger')::float as anger,
                (emotions->>'joy')::float as joy
            FROM sentiment_results
            WHERE message_id LIKE 'test_%'
            ORDER BY created_at DESC
            LIMIT 10
        """)

        results = cur.fetchall()
        if not results:
            print("  ⚠ No sentiment results found yet")
            return False

        for row in results:
            print(f"\n  Message: {row['message_id']}")
            print(f"    Language: {row['language']} → Model: {row['model_language']}")
            print(f"    Sentiment: {row['sentiment']}")
            print(f"    Emotions: joy={row['joy']}, anger={row['anger']}")
            print(f"    Aspects status: {row['aspects_status']}")

            if row['emotion_model_name']:
                print(f"    Emotion model: {row['emotion_model_name']}")

        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def check_ner_results():
    """Check NER extraction results in database."""
    print("\n🔤 Checking NER extraction results...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT
                message_id,
                language,
                model_backend,
                model_language,
                entity_count,
                created_at
            FROM ner_results
            WHERE message_id LIKE 'test_%'
            ORDER BY created_at DESC
            LIMIT 10
        """)

        results = cur.fetchall()
        if not results:
            print("  ⚠ No NER results found yet")
            return False

        for row in results:
            print(f"\n  Message: {row['message_id']}")
            print(f"    Language: {row['language']} → Backend: {row['model_backend']} ({row['model_language']})")
            print(f"    Entities extracted: {row['entity_count']}")

            # Get sample entities
            cur2 = conn.cursor(cursor_factory=RealDictCursor)
            cur2.execute("""
                SELECT entity_text, entity_type, confidence
                FROM ner_entities
                WHERE ner_result_id = (
                    SELECT id FROM ner_results WHERE message_id = %s
                )
                LIMIT 5
            """, (row['message_id'],))

            entities = cur2.fetchall()
            for ent in entities:
                print(f"      - {ent['entity_text']} ({ent['entity_type']}, conf={ent['confidence']:.2f})")
            cur2.close()

        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def check_kafka_output():
    """Check Kafka output topics for enriched events."""
    print("\n📨 Checking Kafka output topics...")

    topics_to_check = ['sentiment.enriched', 'ner.enriched']

    for topic in topics_to_check:
        try:
            consumer = Consumer({
                'bootstrap.servers': KAFKA_BOOTSTRAP,
                'group.id': f'test-consumer-{topic}',
                'auto.offset.reset': 'latest',
                'enable.auto.commit': True,
                'session.timeout.ms': 6000,
            })

            consumer.subscribe([topic])
            print(f"\n  Listening to {topic}...")

            # Wait for a message with timeout
            msg = consumer.poll(timeout=5.0)
            if msg is None:
                print(f"    ⚠ No messages in {topic} yet")
            elif msg.error():
                print(f"    ✗ Error: {msg.error()}")
            else:
                event = json.loads(msg.value().decode('utf-8'))
                print(f"    ✓ Got event from {topic}:")
                print(f"      Message ID: {event.get('message_id')}")
                print(f"      Language: {event.get('language')}")
                if 'sentiment' in event:
                    print(f"      Sentiment: {event.get('sentiment')}")
                    print(f"      Model: {event.get('model', {}).get('language')}")
                if 'entities' in event:
                    print(f"      Entity count: {len(event.get('entities', []))}")
                    print(f"      Backend: {event.get('model', {}).get('backend')}")

            consumer.close()
        except Exception as e:
            print(f"    ✗ Error checking {topic}: {e}")

def health_check():
    """Check service health endpoints."""
    print("\n💚 Service health checks...")
    import urllib.request
    import json as json_lib

    services = {
        'sentiment-analyzer': 'http://localhost:8012/health',
        'ner-extractor': 'http://localhost:8014/health'
    }

    for service, url in services.items():
        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=2) as response:
                health = json_lib.loads(response.read().decode())
                print(f"\n  ✓ {service}:")
                print(f"    Status: {health.get('status', 'unknown')}")
                if 'model_loaded' in health:
                    print(f"    Model loaded: {health['model_loaded']}")
                if 'device' in health:
                    print(f"    Device: {health['device']}")
                if 'backend' in health:
                    print(f"    Backend: {health['backend']}")
        except Exception as e:
            print(f"  ✗ {service}: {e}")

def main():
    print("=" * 60)
    print("🚀 Multilingual ML Pipeline Test")
    print("=" * 60)

    # Health check first
    health_check()
    time.sleep(2)

    # Send test messages
    if not send_test_messages():
        print("\n✗ Failed to send test messages")
        sys.exit(1)

    # Wait for processing
    print("\n⏳ Waiting for messages to be processed (15 seconds)...")
    for i in range(15, 0, -1):
        sys.stdout.write(f'\r  {i} seconds remaining...')
        sys.stdout.flush()
        time.sleep(1)
    print("\n")

    # Check results
    sentiment_ok = check_sentiment_results()
    ner_ok = check_ner_results()
    check_kafka_output()

    # Summary
    print("\n" + "=" * 60)
    if sentiment_ok and ner_ok:
        print("✓ Test completed successfully!")
    else:
        print("⚠ Test partially completed (some results still being processed)")
    print("=" * 60)

if __name__ == '__main__':
    main()
