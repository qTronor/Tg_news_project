#!/bin/bash
# Send test messages to raw.messages Kafka topic via docker

docker exec telegram-news-kafka bash << 'KAFKACMD'
# Russian NER test
echo '{"id":"test_ru_ner_001","text":"Президент России Владимир Путин встретился с премьер-министром Великобритании Кейр Стармером в Москве.","source":"test","language":"ru","timestamp":"2026-04-22T07:00:00Z"}' | kafka-console-producer --broker-list kafka:9092 --topic raw.messages --property "key.serializer=org.apache.kafka.common.serialization.StringSerializer" --property "parse.key=true" --property "key.separator=:" << 'KEYEOF'
test_ru_ner_001:
KEYEOF

# English NER test  
echo '{"id":"test_en_ner_001","text":"The President of the United States Joe Biden met with the UK Prime Minister Keir Starmer in London yesterday.","source":"test","language":"en","timestamp":"2026-04-22T07:00:00Z"}' | kafka-console-producer --broker-list kafka:9092 --topic raw.messages 2>&1 | head -5

# Russian sentiment positive
echo '{"id":"test_ru_sent_pos","text":"Отличное решение! Очень доволен результатами. Рекомендую всем друзьям!","source":"test","language":"ru","timestamp":"2026-04-22T07:00:00Z"}' | kafka-console-producer --broker-list kafka:9092 --topic raw.messages 2>&1 | head -5

# English sentiment positive
echo '{"id":"test_en_sent_pos","text":"Absolutely thrilled with this product! Exceeded all my expectations. Very happy!","source":"test","language":"en","timestamp":"2026-04-22T07:00:00Z"}' | kafka-console-producer --broker-list kafka:9092 --topic raw.messages 2>&1 | head -5

KAFKACMD
