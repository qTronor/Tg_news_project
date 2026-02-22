Изучу существующий сервис ingestion и выведу стандарты проекта. Начну с анализа структуры репозитория.

[25 tools called]

Отлично, изучил структуру проекта. Теперь дам строго структурированные выводы по стандартам проекта:

---

## **1. Структура репо и как добавлять новый сервис**

### Текущая структура:
```
Tg_news_project/
└── rbc_telegram_collector/          # Единственный сервис
    ├── collector/                    # Основной код (пакет)
    │   ├── sources/                  # Источники данных (plugin pattern)
    │   │   ├── base.py              # Абстрактный Source
    │   │   └── telegram.py
    │   ├── sinks/                    # Приемники данных (plugin pattern)
    │   │   ├── base.py              # Абстрактный Sink
    │   │   ├── jsonl.py
    │   │   ├── csv_sink.py
    │   │   └── rabbitmq_sink.py     # Пример для брокера
    │   ├── config.py                 # Pydantic модели конфигурации
    │   ├── models.py                 # Доменные модели (CollectedMessage)
    │   ├── state.py                  # Управление состоянием (incremental load)
    │   ├── cli.py                    # CLI интерфейс (argparse)
    │   └── runner.py                 # Основная логика сбора
    ├── data/                         # Выходные файлы (монтируется в volume)
    ├── state/                        # Состояние обработки (монтируется)
    ├── config.yaml                   # Основной конфиг
    ├── config.example.yaml           # Шаблон конфига
    ├── config.microservice.example.yaml
    ├── requirements.txt
    ├── Dockerfile
    ├── docker-compose.yml            # Для standalone запуска
    ├── docker-compose.microservice.yml  # Для работы с брокером
    ├── main.py                       # Entry point (вызывает cli)
    └── README.md
```

### Рекомендации для нового сервиса:

**Naming**: `<назначение>_<технология>_<тип>` (например: `news_kafka_consumer`, `sentiment_ml_processor`)

**Структура нового сервиса**:
```
<service_name>/
├── <service_name>/              # Основной пакет (то же имя)
│   ├── __init__.py
│   ├── config.py                # Pydantic Settings
│   ├── models.py                # Доменные модели
│   ├── cli.py                   # CLI (опционально)
│   ├── runner.py / service.py   # Основная логика
│   └── [sources/sinks/...]      # Если нужна plugin-архитектура
├── data/                        # Если нужно локальное хранение
├── config.yaml
├── config.example.yaml
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── main.py                      # Entry point
└── README.md
```

**Важно**: Каждый сервис — отдельная папка верхнего уровня в монорепе.

---

## **2. Конфигурация**

### Библиотеки:
- **Pydantic v2.6+** (для валидации)
- **pydantic-settings v2.2.1+** (для env vars)
- **PyYAML v6.0.1+** (для файлов конфигурации)

### Паттерн:

**config.py**:
```python
from pydantic import BaseModel, Field
from typing import Optional, List, Literal

class ChannelConfig(BaseModel):
    name: str = Field(..., description="Username without @")
    enabled: bool = True
    since: Optional[date] = None
    limit: Optional[int] = 2000

class OutputConfig(BaseModel):
    data_dir: str = "data"
    state_dir: str = "state"
    formats: List[Literal["jsonl", "csv"]] = ["jsonl"]

class LoggingConfig(BaseModel):
    level: str = "INFO"

class AppConfig(BaseModel):
    channels: List[ChannelConfig]
    output: OutputConfig = OutputConfig()
    logging: LoggingConfig = LoggingConfig()
```

**Загрузка**:
```python
import yaml
from pathlib import Path

def load_config(path: Path) -> AppConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)
```

### Environment Variables:

**Naming convention**: `<СЕРВИС>_<ПАРАМЕТР>` (все в UPPERCASE)

**Примеры из проекта**:
- `TG_API_ID` — ID Telegram API
- `TG_API_HASH` — Hash Telegram API
- `TG_STRING_SESSION` — Сессия (для неинтерактивного режима)
- `BROKER_HOST` — (для микросервиса)
- `BROKER_PORT` — (для микросервиса)

**Приоритет**: ENV vars > config.yaml > defaults

### Файлы конфигурации:
- `config.example.yaml` — шаблон с комментариями (в git)
- `config.yaml` — реальный конфиг (в .gitignore)
- `config.microservice.example.yaml` — для режима с брокером

---

## **3. Kafka / Брокеры сообщений**

### Библиотека:

**Kafka не используется в текущем проекте**, но есть подготовка:
- **RabbitMQ**: `pika >= 1.3.0` (реализован `rabbitmq_sink.py`)
- В документах упоминается **kafka-python >= 2.0.0** как альтернатива

### Паттерн Publisher (Producer):

**Архитектура**: Sink pattern (абстракция `base.py`)

**RabbitMQ пример** (`rabbitmq_sink.py`):
```python
class RabbitMQSink(Sink):
    def write(self, items: Iterable[CollectedMessage]) -> int:
        # Connect (lazy)
        if self._connection is None or self._connection.is_closed:
            self._connect()
        
        count = 0
        for item in items:
            message_body = json.dumps(item.to_dict(), ensure_ascii=False, default=str)
            routing_key = self.routing_key_template.format(channel=item.channel, source=item.source)
            
            self._channel.basic_publish(
                exchange=self.exchange,
                routing_key=routing_key,
                body=message_body.encode("utf-8"),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # Persistent
                    content_type="application/json",
                    headers={"source": item.source, "channel": item.channel, ...}
                )
            )
            count += 1
        
        return count
```

**Конфигурация брокера**:
```yaml
broker:
  type: "rabbitmq"
  host: "rabbitmq"
  port: 5672
  username: "guest"
  password: "guest"
  virtual_host: "/"
  exchange: "telegram_messages"
  routing_key_template: "{channel}"  # Dynamic routing
```

### Consumer / Retry / DLQ:

**НЕ РЕАЛИЗОВАНО** в текущем проекте. Проект — только producer (ingestion).

**Рекомендации из документации**:
- Для consumer — использовать `basic_consume` с `auto_ack=False`
- Manual acknowledge: `ch.basic_ack(delivery_tag=method.delivery_tag)`
- Retry/DLQ — **не упоминается**, нужно добавлять самостоятельно

---

## **4. Логирование / Метрики / Трассировка**

### Логирование:

**Библиотека**: Стандартный `logging` (stdlib)

**Инициализация**:
```python
logging.basicConfig(
    level=getattr(logging, level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
```

**Использование**:
```python
log = logging.getLogger("collector")  # или __name__
log.info("Collecting channel=%s since=%s min_id=%s limit=%s", ...)
log.error("Error writing to %s: %s", path, e, exc_info=True)
```

**Уровень**: Задается через `config.yaml`:
```yaml
logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR
```

**Стиль логов**: Структурированные сообщения с параметрами (`key=value`)

### Метрики:

**НЕ РЕАЛИЗОВАНО**. В документах упоминается:
- Планируется Prometheus
- Метрики: количество собранных сообщений, время последнего сбора, ошибки подключения

### Трассировка:

**НЕ РЕАЛИЗОВАНО**. Нет упоминаний OpenTelemetry, Jaeger и т.д.

---

## **5. Тесты**

**ТЕСТОВ НЕТ**. 

Нет файлов:
- `test_*.py`
- `pytest.ini`
- `setup.py`
- `conftest.py`

**Рекомендация**: Создать структуру:
```
<service_name>/
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_sinks.py
│   └── test_sources.py
├── pytest.ini
└── requirements-dev.txt  # pytest, pytest-asyncio, pytest-cov
```

**Команда запуска** (предполагаемая):
```bash
pytest tests/
# или
python -m pytest tests/ -v --cov=collector
```

---

## **6. Docker / Compose: Как добавить новый контейнер**

### Текущая структура Dockerfile:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY collector /app/collector
COPY main.py /app/main.py
COPY config.example.yaml /app/config.example.yaml

ENTRYPOINT ["python", "-m", "collector.cli"]
CMD ["collect", "--config", "config.yaml"]
```

**Паттерн**:
1. Python 3.11-slim (базовый образ)
2. WORKDIR `/app`
3. Сначала `requirements.txt` (кэширование слоев)
4. Затем код
5. ENTRYPOINT = модуль Python (`-m <package>.cli`)

### Docker Compose:

**Standalone** (`docker-compose.yml`):
```yaml
services:
  telegram-collector:
    build: .
    environment:
      TG_API_ID: "${TG_API_ID}"
      TG_API_HASH: "${TG_API_HASH}"
      TG_STRING_SESSION: "${TG_STRING_SESSION}"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - ./data:/app/data
      - ./state:/app/state
```

**Микросервис** (`docker-compose.microservice.yml`):
```yaml
services:
  rabbitmq:
    image: rabbitmq:3-management-alpine
    container_name: telegram-collector-rabbitmq
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  telegram-collector:
    build: .
    container_name: telegram-collector-service
    depends_on:
      rabbitmq:
        condition: service_healthy
    environment:
      TG_API_ID: "${TG_API_ID}"
      TG_API_HASH: "${TG_API_HASH}"
      TG_STRING_SESSION: "${TG_STRING_SESSION}"
      BROKER_HOST: "rabbitmq"
      BROKER_PORT: "5672"
    volumes:
      - ./config.microservice.yaml:/app/config.yaml:ro
      - ./state:/app/state
      - ./data:/app/data
    command: ["python", "-m", "collector.service"]
    restart: unless-stopped

volumes:
  rabbitmq_data:
```

### Добавление нового контейнера:

**Рекомендации**:
1. **Naming**: `<service>-<component>` (например, `telegram-collector-rabbitmq`)
2. **Healthcheck**: Обязательно для зависимостей (`depends_on: service_healthy`)
3. **Volumes**: Named volumes для данных, bind mounts для конфигов (`:ro` для read-only)
4. **Environment**: Через `.env` файл (не хардкодить)
5. **Restart policy**: `unless-stopped` для долгоживущих сервисов
6. **Networks**: Не указаны (default network), но для production лучше явно создавать

**Шаблон нового сервиса**:
```yaml
  my-new-service:
    build: ./my_service_folder
    container_name: my-new-service
    depends_on:
      rabbitmq:
        condition: service_healthy
    environment:
      SERVICE_VAR: "${SERVICE_VAR}"
      BROKER_HOST: "rabbitmq"
    volumes:
      - ./my_service_folder/config.yaml:/app/config.yaml:ro
      - ./my_service_folder/data:/app/data
    command: ["python", "-m", "my_service.cli", "run"]
    restart: unless-stopped
```

---

## **7. Мини-шаблон "Service Skeleton"**

### Список файлов и их содержимое:

```
<service_name>/
├── <service_name>/
│   ├── __init__.py                 # Пустой или с __version__
│   ├── models.py                   # Pydantic models (доменные сущности)
│   │   └── @dataclass CollectedMessage / Event / etc.
│   ├── config.py                   # Pydantic BaseSettings (валидация конфига)
│   │   └── AppConfig, OutputConfig, LoggingConfig, BrokerConfig
│   ├── state.py                    # StateStore (JSON файл с last_id и т.д.)
│   ├── cli.py                      # CLI интерфейс (argparse)
│   │   └── build_parser(), cmd_*, main()
│   ├── runner.py                   # Основная бизнес-логика (async def collect_once)
│   ├── sources/                    # (опционально) Plugin pattern для источников
│   │   ├── base.py                # ABC Source
│   │   └── <concrete>.py
│   └── sinks/                      # (опционально) Plugin pattern для приемников
│       ├── base.py                # ABC Sink
│       └── <concrete>.py
├── data/                           # Output data (gitignore, volume)
├── state/                          # State files (gitignore, volume)
├── config.yaml                     # Рабочий конфиг (gitignore)
├── config.example.yaml             # Шаблон конфига (в git, с комментариями)
├── config.microservice.example.yaml # (если есть режим с брокером)
├── requirements.txt                # Зависимости (pin versions: pkg>=X.Y.Z)
├── Dockerfile                      # python:3.11-slim, WORKDIR /app
├── docker-compose.yml              # Standalone режим
├── docker-compose.microservice.yml # С брокером (опционально)
├── main.py                         # Entry point: from <service>.cli import main
├── README.md                       # Документация (quick start, config, docker)
└── .gitignore                      # *.session, config.yaml, data/, state/, __pycache__
```

### Минимальное содержимое файлов:

**`main.py`**:
```python
from <service_name>.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

**`<service_name>/cli.py`**:
```python
import argparse

def cmd_run(args: argparse.Namespace) -> int:
    from <service_name>.runner import run_service
    return run_service(args.config)

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="<service_name>")
    sub = p.add_subparsers(dest="cmd", required=True)
    
    p_run = sub.add_parser("run", help="Run service")
    p_run.add_argument("--config", default="config.yaml")
    p_run.set_defaults(func=cmd_run)
    
    return p

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
```

**`<service_name>/config.py`**:
```python
from pydantic import BaseModel, Field
from typing import List, Optional

class LoggingConfig(BaseModel):
    level: str = "INFO"

class AppConfig(BaseModel):
    logging: LoggingConfig = LoggingConfig()
    # ... остальные секции
```

**`<service_name>/runner.py`**:
```python
import asyncio
import logging
from pathlib import Path
import yaml
from <service_name>.config import AppConfig

def load_config(path: Path) -> AppConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)

def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

async def process_once(cfg: AppConfig):
    log = logging.getLogger("<service_name>")
    # Основная логика
    log.info("Processing...")

def run_service(config_path: str) -> int:
    cfg = load_config(Path(config_path))
    _setup_logging(cfg.logging.level)
    asyncio.run(process_once(cfg))
    return 0
```

**`<service_name>/models.py`**:
```python
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Any

@dataclass(frozen=True)
class DomainEvent:
    id: str
    timestamp: datetime
    data: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d
```

**`Dockerfile`**:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY <service_name> /app/<service_name>
COPY main.py /app/main.py
COPY config.example.yaml /app/config.example.yaml

ENTRYPOINT ["python", "-m", "<service_name>.cli"]
CMD ["run", "--config", "config.yaml"]
```

**`docker-compose.yml`**:
```yaml
services:
  <service_name>:
    build: .
    environment:
      SERVICE_VAR: "${SERVICE_VAR}"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - ./data:/app/data
      - ./state:/app/state
```

**`requirements.txt`**:
```
pydantic>=2.6.0
pydantic-settings>=2.2.1
PyYAML>=6.0.1
```

**`README.md`**:
```markdown
# <Service Name>

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   cp config.example.yaml config.yaml
   ```

2. Configure environment variables:
   ```bash
   export SERVICE_VAR="value"
   ```

3. Run:
   ```bash
   python -m <service_name>.cli run --config config.yaml
   ```

## Docker

```bash
docker-compose up
```
```

---

## **Итоговые выводы**

### Что ЕСТЬ в проекте:
✅ Pydantic для конфигурации (v2)  
✅ YAML конфиги с примерами  
✅ Env vars (`TG_*`, `BROKER_*`)  
✅ Plugin архитектура (sources/sinks)  
✅ Логирование через stdlib  
✅ Docker + Compose (2 режима)  
✅ State management (incremental)  
✅ RabbitMQ Sink (пример publisher)  

### Что ОТСУТСТВУЕТ:
❌ Kafka (только упоминание)  
❌ Consumer паттерны  
❌ Retry / DLQ логика  
❌ Метрики (Prometheus)  
❌ Трассировка (OpenTelemetry)  
❌ Тесты (pytest)  
❌ CI/CD конфиги  

### Ключевые принципы для новых сервисов:
1. **Монорепо**: каждый сервис = отдельная папка верхнего уровня
2. **Naming**: `<назначение>_<технология>_<тип>`
3. **Конфиг**: YAML + Pydantic + env vars
4. **Логи**: stdlib logging, формат `"%(asctime)s %(levelname)s %(name)s: %(message)s"`
5. **Docker**: `python:3.11-slim`, volumes для data/state/config
6. **Архитектура**: CLI → Runner → Sources/Sinks (plugin pattern)
7. **State**: JSON файлы для incremental processing