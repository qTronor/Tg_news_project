#!/usr/bin/env python3
"""Test script to send multilingual messages to Kafka for analysis."""

import json
from datetime import datetime
from confluent_kafka import Producer

# Kafka config
bootstrap_servers = "localhost:9092"
topic = "raw.messages"

producer = Producer({
    'bootstrap.servers': bootstrap_servers,
    'client.id': 'test-producer'
})

test_messages = [
    {
        "id": "test_ru_001",
        "text": "Президент России провел встречу с премьер-министром. Обсуждались вопросы экономики и развития инфраструктуры.",
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
        "id": "test_ru_sentiment",
        "text": "Это отличное решение! Я очень доволен результатами и рекомендую это всем своим друзьям.",
        "source": "test",
        "language": "ru",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    },
    {
        "id": "test_en_sentiment",
        "text": "I'm absolutely thrilled with this product! It exceeded all my expectations and I'm very happy.",
        "source": "test",
        "language": "en",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    },
]

print(f"Sending {len(test_messages)} test messages to Kafka topic '{topic}'...")

for msg in test_messages:
    try:
        producer.produce(
            topic,
            key=msg["id"].encode('utf-8'),
            value=json.dumps(msg).encode('utf-8')
        )
        print(f"✓ Sent: {msg['id']} ({msg['language']}) - {msg['text'][:50]}...")
    except Exception as e:
        print(f"✗ Failed to send {msg['id']}: {e}")

producer.flush()
print("\nAll messages sent successfully!")
