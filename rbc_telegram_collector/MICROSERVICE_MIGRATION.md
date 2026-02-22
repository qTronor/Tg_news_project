# План миграции в микросервис

## Этап 1: Добавление поддержки брокера сообщений

### 1.1 Установить зависимости

Добавить в `requirements.txt`:
```
pika>=1.3.0  # для RabbitMQ
# или
kafka-python>=2.0.0  # для Kafka
# или
redis>=5.0.0  # для Redis Streams
```

### 1.2 Создать sink для брокера

См. пример `collector/sinks/rabbitmq_sink.py`

### 1.3 Обновить конфигурацию

Добавить секцию `broker` в `config.py`:
```python
class BrokerConfig(BaseModel):
    type: Literal["rabbitmq", "kafka", "redis"] = "rabbitmq"
    host: str = "localhost"
    port: int = 5672
    username: Optional[str] = None
    password: Optional[str] = None
    exchange: str = "telegram_messages"
    routing_key_template: str = "{channel}"
```

### 1.4 Обновить runner.py

Модифицировать `collect_once()` для использования брокера:
```python
if cfg.broker:
    sink = RabbitMQSink(...)
    sink.write(items)
```

## Этап 2: Долгоживущий сервис

### 2.1 Создать service.py

Новый модуль для запуска как сервис:
```python
# collector/service.py
import asyncio
import signal
from collector.runner import collect_once
from collector.config import load_config

class CollectorService:
    def __init__(self, config_path: str):
        self.config = load_config(config_path)
        self.running = True
    
    async def run_loop(self):
        while self.running:
            await collect_once(self.config)
            await asyncio.sleep(self.config.scheduler.interval_seconds)
    
    def stop(self):
        self.running = False

if __name__ == "__main__":
    service = CollectorService("config.yaml")
    # Обработка сигналов для graceful shutdown
    signal.signal(signal.SIGINT, lambda s, f: service.stop())
    signal.signal(signal.SIGTERM, lambda s, f: service.stop())
    asyncio.run(service.run_loop())
```

## Этап 3: REST API (опционально)

### 3.1 Добавить FastAPI

```python
# collector/api.py
from fastapi import FastAPI
from collector.runner import collect_once

app = FastAPI()

@app.post("/collect")
async def trigger_collect():
    # Запустить сбор по запросу
    results = await collect_once(config)
    return {"status": "ok", "results": results}

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

## Этап 4: Метрики и мониторинг

Добавить Prometheus метрики:
- Количество собранных сообщений
- Время последнего сбора
- Ошибки подключения к брокеру

## Пример использования

### Запуск с RabbitMQ:

1. Запустить RabbitMQ:
```bash
docker-compose -f docker-compose.microservice.yml up rabbitmq -d
```

2. Запустить collector:
```bash
docker-compose -f docker-compose.microservice.yml up telegram-collector
```

3. Проверить сообщения в RabbitMQ:
```bash
# Установить rabbitmqadmin или использовать Management UI на http://localhost:15672
rabbitmqadmin get queue=telegram_messages_queue
```

### Потребитель сообщений (пример на Python):

```python
import pika
import json

connection = pika.BlockingConnection(
    pika.ConnectionParameters('localhost')
)
channel = connection.channel()

def callback(ch, method, properties, body):
    message = json.loads(body)
    print(f"Received: {message['channel']} - {message['text'][:50]}")
    # Сохранить в БД, обработать и т.д.
    ch.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_consume(
    queue='telegram_messages_queue',
    on_message_callback=callback
)

channel.start_consuming()
```

## Преимущества новой архитектуры

1. **Разделение ответственности**: Collector только собирает, обработка отдельно
2. **Масштабируемость**: Можно запустить несколько consumers
3. **Надежность**: Брокер гарантирует доставку сообщений
4. **Гибкость**: Легко добавить новые обработчики без изменения collector


