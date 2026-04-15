# Тестирование — Telegram News Pipeline

## Обзор

Документ описывает все реализованные тесты проекта, инструменты тестирования, а также план возможных тестов для полного покрытия каждого сервиса.

---

## Стек тестирования

| Инструмент | Версия | Область |
|-----------|--------|---------|
| pytest | ≥ 8.3 | Backend unit/integration/smoke-тесты (Python) |
| pytest-asyncio | ≥ 0.23 | Асинхронные тесты для aiohttp/aiokafka |
| Jest | 30.x | Frontend unit-тесты (TypeScript/React) |
| @testing-library/react | 16.x | Тестирование React-компонентов |
| @testing-library/jest-dom | 6.x | DOM-матчеры для Jest |
| @testing-library/user-event | 14.x | Эмуляция пользовательских взаимодействий |
| Playwright | 1.58+ | Frontend E2E-тесты (браузер) |
| ts-jest | 29.x | Трансформация TypeScript для Jest |
| PowerShell / Bash | — | Инфраструктурные smoke-тесты |

---

## Реализованные тесты

### 1. Frontend — Unit-тесты (Jest)

**Конфигурация:** `frontend/jest.config.js`
**Setup:** `frontend/jest.setup.ts` (импорт `@testing-library/jest-dom`)

#### 2.1 Token Management

**Файл:** `frontend/src/__tests__/auth.test.ts`

| Тест-кейс | Описание |
|-----------|----------|
| `returns null tokens when nothing stored` | localStorage пуст → `access` и `refresh` равны `null` |
| `stores and retrieves tokens` | `storeTokens()` сохраняет → `getStoredTokens()` возвращает корректно |
| `clears all tokens` | `clearTokens()` → все токены удалены |

#### 2.2 Utility Functions

**Файл:** `frontend/src/__tests__/utils.test.ts`

| Функция | Тест-кейсы |
|---------|-----------|
| `formatNumber` | Значения < 1K, тысячи (K), миллионы (M) |
| `sentimentColor` | Цвет для positive (> 0.2), negative (< −0.2), neutral |
| `sentimentLabel` | Строковая метка: Positive / Negative / Neutral |
| `entityTypeColor` | Цвет для PER, ORG, LOC, MISC, неизвестных типов |

**Запуск:**
```bash
cd frontend
npm test
```

---

### 2. Frontend — E2E-тесты (Playwright)

**Файл:** `frontend/e2e/auth.spec.ts`
**Конфигурация:** `frontend/playwright.config.ts`
**Браузер:** Chromium
**Base URL:** `http://localhost:3000`

#### 3.1 Authentication

| Тест-кейс | Действия | Ожидание |
|-----------|---------|----------|
| Login page renders | Переход на `/login` | Заголовок "TG News Analytics", кнопка "Войти" |
| Invalid credentials | Ввод неверных данных → клик "Войти" | Отображается `.text-destructive` |
| Switch login/register | Клик на "Регистрация" | Видны поля email, username |
| Forgot password | Клик "Забыли пароль?" | Переход на `/forgot-password` |
| Successful login | Ввод корректных данных → клик "Войти" | Редирект на `/`, заголовок "Dashboard" |

#### 3.2 Navigation

| Тест-кейс | Действия | Ожидание |
|-----------|---------|----------|
| Sidebar navigation | Клик по ссылкам: Лента, Темы, Сущности | URL `/feed`, `/topics`, `/entities` |

**Запуск:**
```bash
cd frontend
npx playwright install
npx playwright test
```

---

### 4. Инфраструктурный Smoke-тест (PowerShell)

**Файл:** `scripts/smoke_test.ps1`

Полный pipeline-тест инфраструктуры:

| Шаг | Действие | Проверка |
|-----|---------|----------|
| B | `docker compose up -d` | Healthcheck всех контейнеров (postgres, neo4j, kafka, redis…) |
| C | Миграция PostgreSQL | Таблицы созданы (`raw_messages` и др.) |
| C | Инициализация Neo4j | Constraints/indexes применены |
| D | Создание Kafka-топиков | Топики из `kafka/topics.yml` |
| E | Валидация JSON Schema | Все `.schema.json` валидны, примеры проходят валидацию |
| F | Публикация raw-события | Событие успешно отправлено и прочитано из `raw.telegram.messages` |
| F | Повторная отправка | Проверка идемпотентности (на уровне Kafka) |

**Запуск:**
```powershell
powershell -ExecutionPolicy Bypass -File scripts/smoke_test.ps1
```

---

### 5. Preprocessor — Smoke-тест (Bash)

**Файл:** `preprocessor/scripts/smoke_test.sh`

| Шаг | Действие | Проверка |
|-----|---------|----------|
| 1 | Отправка raw-события в Kafka | Событие опубликовано |
| 2 | Ожидание preprocessed output | Сообщение появилось в `preprocessed.messages` |
| 3 | Проверка БД | Строка в `preprocessed_messages` с корректными полями |

**Запуск:**
```bash
bash preprocessor/scripts/smoke_test.sh
```

---

## Конфигурации тестирования

### Jest (Frontend)

```javascript
// frontend/jest.config.js
{
  testEnvironment: "jsdom",
  transform: { "^.+\\.tsx?$": ["ts-jest", { tsconfig: "tsconfig.json", jsx: "react-jsx" }] },
  moduleNameMapper: { "^@/(.*)$": "<rootDir>/src/$1" },
  testPathIgnorePatterns: ["/node_modules/", "/.next/", "/e2e/"]
}
```

### Playwright (Frontend E2E)

```typescript
// frontend/playwright.config.ts
{
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: "html",
  use: { baseURL: "http://localhost:3000", trace: "on-first-retry" },
  projects: [{ name: "chromium", use: devices["Desktop Chrome"] }],
  webServer: { command: "npm run dev", url: "http://localhost:3000" }
}
```

---

## Возможные тесты (план расширения)

### 1. Auth Service (FastAPI) — Unit-тесты

**Путь:** `auth_service/tests/`
**Зависимости:** `pytest`, `pytest-asyncio`, `httpx` (AsyncClient)

| Модуль | Тест-кейсы |
|--------|-----------|
| Регистрация | Успешная регистрация, дубликат email, невалидный формат, слабый пароль |
| Аутентификация | Корректный логин → JWT, неверный пароль → 401, несуществующий пользователь → 401 |
| JWT | Генерация access/refresh token, валидация claims (exp, sub), expired token → 401 |
| Refresh | Обновление access по refresh token, повторное использование refresh → 401 (rotation) |
| Logout | Blacklist токена в Redis, повторный запрос с blacklisted token → 401 |
| Профиль | `GET /me` → данные пользователя, `PUT /me` → обновление, `change-password` |
| Email | Отправка verification email (mock SMTP), верификация по коду, forgot/reset password |
| Rate Limiting | Превышение лимита запросов → 429 |
| Admin | CRUD каналов, audit-log, доступ без admin role → 403 |

```python
# Пример: auth_service/tests/test_auth.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_register_success(client):
    resp = await client.post("/api/auth/register", json={
        "email": "test@example.com",
        "username": "testuser",
        "password": "StrongPass123!"
    })
    assert resp.status_code == 201
    assert "access_token" in resp.json()

@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post("/api/auth/login", json={
        "email": "test@example.com",
        "password": "wrong"
    })
    assert resp.status_code == 401
```

---

### 2. Message Persister — Unit/Integration-тесты

**Путь:** `message_persister/tests/`
**Зависимости:** `pytest`, `pytest-asyncio`, `testcontainers` (PostgreSQL, Kafka)

| Категория | Тест-кейсы |
|-----------|-----------|
| Десериализация | Валидное raw-событие → `RawMessage`, невалидный JSON → ошибка |
| Идемпотентность | Повторная вставка event_id → пропуск, запись в `processed_events` |
| Запись в БД | `raw_messages` содержит корректные поля, транзакционность |
| Outbox | Запись в `outbox` таблицу внутри той же транзакции |
| DLQ | Неизвестный формат → отправка в DLQ-топик |
| Health endpoint | `GET /health` → 200 при доступной БД, 503 при недоступной |

```python
# Пример: message_persister/tests/test_persister.py
@pytest.mark.asyncio
async def test_idempotent_insert(db_pool, sample_event):
    from message_persister.persister import persist_message
    result1 = await persist_message(db_pool, sample_event)
    assert result1 is True
    result2 = await persist_message(db_pool, sample_event)
    assert result2 is False  # дубликат — пропущен
```

---

### 3. Preprocessor — Unit/Integration-тесты

**Путь:** `preprocessor/tests/`

| Категория | Тест-кейсы |
|-----------|-----------|
| Нормализация текста | Удаление HTML-тегов, нормализация пробелов, Unicode-очистка |
| Токенизация | Корректный подсчёт слов, обработка спецсимволов |
| Языковое определение | Русский текст → `ru`, смешанный текст → fallback |
| Kafka round-trip | Consume raw → produce preprocessed (с testcontainers-kafka) |
| Пустое сообщение | `text: ""` → обработка без ошибок, `word_count: 0` |
| Длинный текст | Текст > 100K символов → усечение или корректная обработка |

---

### 4. Sentiment Analyzer — Unit/Integration-тесты

**Путь:** `sentiment_analyzer/tests/`

| Категория | Тест-кейсы |
|-----------|-----------|
| Модель | Загрузка RuBERT, warm-up inference |
| Inference | Позитивный текст → score > 0.5, негативный → score < −0.5, нейтральный → ≈ 0 |
| Батч-обработка | N сообщений → N результатов, порядок сохранён |
| Ошибки | Пустой текст → default neutral, слишком длинный текст → truncation |
| Output schema | Результат соответствует `sentiment_enriched.schema.json` |
| Производительность | ≤ 500ms на одно сообщение (benchmark) |

---

### 5. NER Extractor — Unit/Integration-тесты

**Путь:** `ner_extractor/tests/`

| Категория | Тест-кейсы |
|-----------|-----------|
| Natasha Pipeline | Инициализация, прогрев |
| Извлечение PER | "Путин заявил…" → `PER: ["Путин"]` |
| Извлечение ORG | "…ЦБ РФ повысил ставку…" → `ORG: ["ЦБ РФ"]` |
| Извлечение LOC | "…в Москве прошёл…" → `LOC: ["Москва"]` |
| Без сущностей | Текст без NE → пустые списки |
| Дедупликация | Одно имя упомянуто 3 раза → одна сущность |
| Output schema | Результат соответствует `ner_enriched.schema.json` |

---

### 6. Topic Clusterer — Unit/Integration-тесты

**Путь:** `topic_clusterer/tests/`

| Категория | Тест-кейсы |
|-----------|-----------|
| Embeddings | SBERT генерирует вектора корректной размерности |
| UMAP | Снижение размерности N×768 → N×D (D < 768) |
| HDBSCAN | ≥ 2 кластера на реалистичных данных, noise-точки помечены как −1 |
| Малый датасет | < 10 документов → fallback: 1 кластер или без кластеризации |
| Topic Label | Каждый кластер получает метку |
| Round-trip | Consume → embed → cluster → produce (с mock Kafka) |

---

### 7. Collector (Telethon) — Unit-тесты

**Путь:** `rbc_telegram_collector/tests/`

| Категория | Тест-кейсы |
|-----------|-----------|
| Config | Валидация YAML-конфига (Pydantic), невалидные поля → ошибка |
| Models | `CollectedMessage.to_dict()` — корректная сериализация |
| State | Сохранение/загрузка `last_id` из JSON-файла |
| JSONL Sink | Запись N сообщений → N строк в файле, каждая — валидный JSON |
| CSV Sink | Запись → корректный CSV с заголовками |
| RabbitMQ Sink | Mock-соединение → `basic_publish` вызван N раз, persistent delivery |
| CLI | `--config` → корректная загрузка, `--help` → exit 0 |

---

### 8. Frontend — Расширенные Unit-тесты

**Путь:** `frontend/src/__tests__/`

| Компонент | Тест-кейсы |
|-----------|-----------|
| `AuthProvider` | Login → состояние authenticated, logout → unauthenticated, refresh → новый token |
| `TimeRangeContext` | Пресеты 1h/6h/24h/7d/30d → корректные from/to |
| `DemoContext` | Переключение demo/live → переключение источника данных |
| `I18nContext` | Смена ru/en → строки переводятся |
| `useOverview` | Mock API → корректный парсинг, ошибка API → error state |
| `useTopics` | Polling каждые N секунд (fake timers) |
| `DashboardPage` | Рендеринг KPI-карт, графиков при mock-данных |
| `FeedPage` | Фильтрация по каналу, поиск по тексту |
| `GraphPage` | Cytoscape-граф рендерится с узлами и рёбрами |
| `LoginForm` | Валидация email формата, минимальная длина пароля |
| `Sidebar` | Активная ссылка подсвечена, навигация при клике |

---

### 9. Frontend — Расширенные E2E-тесты (Playwright)

**Путь:** `frontend/e2e/`

| Сценарий | Действия | Ожидание |
|----------|---------|----------|
| Dashboard KPIs | Login → Dashboard | KPI-карты отображают числа ≥ 0 |
| Sentiment Chart | Dashboard → проверка графика | SVG-элементы Recharts видны |
| Feed — Фильтры | `/feed` → выбор канала → фильтрация | Кол-во сообщений изменяется |
| Feed — Live Mode | Включение live-режима | Новые сообщения появляются автоматически |
| Topics List | `/topics` → клик на кластер | Переход на `/topics/{id}`, документы отображаются |
| Entities Table | `/entities` → фильтр по типу PER | Только персоны в таблице |
| Entity Profile | `/entities/{id}` | Профиль с именем, типом, упоминаниями |
| Graph View | `/graph` | Cytoscape canvas рендерится, узлы кликабельны |
| Settings | `/settings` → смена API URL | Сохранение в localStorage |
| Theme Toggle | Переключение light/dark | CSS-переменные изменяются |
| Locale Switch | Переключение ru/en | Тексты меняют язык |
| Admin Channels | Login admin → `/admin/channels` | Таблица каналов, toggle видимости |
| Responsive | Viewport 375×667 (mobile) | Sidebar скрыт, hamburger-меню работает |
| Registration | Полный цикл: register → verify email → login | Успешный вход |
| Password Reset | Forgot → email → reset → login | Новый пароль работает |

---

### 10. JSON Schema — Контрактные тесты

**Путь:** `tests/contracts/`

| Тест-кейс | Описание |
|-----------|----------|
| Schema validity | Каждый `*.schema.json` — валидная JSON Schema (Draft-07/2020-12) |
| Example validation | Каждый `*.example.json` проходит валидацию по соответствующей схеме |
| Required fields | Удаление обязательного поля → `ValidationError` |
| Extra fields | Дополнительные поля → проходит (если `additionalProperties: true`) или нет |
| Type mismatch | Неверный тип поля → `ValidationError` |
| Inter-schema | Output одного сервиса = Input следующего (chain: raw → persisted → preprocessed → enriched) |

```python
# Пример: tests/contracts/test_schemas.py
import json, glob
from pathlib import Path
from jsonschema import validate, Draft202012Validator

SCHEMAS_DIR = Path("schemas")
EXAMPLES_DIR = Path("examples")

@pytest.mark.parametrize("schema_path", sorted(SCHEMAS_DIR.glob("*.schema.json")))
def test_schema_is_valid(schema_path):
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)

@pytest.mark.parametrize("schema_path", sorted(SCHEMAS_DIR.glob("*.schema.json")))
def test_example_matches_schema(schema_path):
    schema = json.loads(schema_path.read_text())
    example_name = schema_path.stem.replace(".schema", ".example") + ".json"
    example_path = EXAMPLES_DIR / example_name
    if not example_path.exists():
        pytest.skip(f"No example for {schema_path.name}")
    example = json.loads(example_path.read_text())
    validate(instance=example, schema=schema)
```

---

### 11. Инфраструктурные тесты (Docker / Kafka / DB)

| Категория | Тест-кейсы |
|-----------|-----------|
| Docker health | Все контейнеры `healthy` после `docker compose up` |
| Kafka topics | Все топики из `kafka/topics.yml` созданы |
| PG migrations | Все таблицы из `001_initial_schema.sql` и `002_auth_schema.sql` существуют |
| Neo4j constraints | Constraints из `init.cypher` применены |
| Redis connection | `PING` → `PONG` |
| Network isolation | Сервисы видят друг друга по имени контейнера |

---

### 12. Нагрузочное тестирование

**Инструмент:** Locust / k6

| Сценарий | Метрика | Порог |
|----------|---------|-------|
| Analytics API — `/overview/clusters` | p95 latency | < 500 ms |
| Analytics API — `/entities/top` | p95 latency | < 300 ms |
| Analytics API — `/sentiment/dynamics` | p95 latency | < 500 ms |
| Auth Service — `/login` | p95 latency | < 200 ms |
| Auth Service — `/register` | p95 latency | < 300 ms |
| Kafka throughput | messages/sec | > 1000 msg/s |
| Pipeline E2E latency | raw → sentiment.enriched | < 5 s (p95) |

```python
# Пример: tests/load/locustfile.py
from locust import HttpUser, task, between

class AnalyticsUser(HttpUser):
    wait_time = between(1, 3)
    
    @task(3)
    def overview(self):
        self.client.get("/analytics/overview/clusters", params={
            "from": "2026-01-01", "to": "2026-01-31"
        })
    
    @task(2)
    def entities_top(self):
        self.client.get("/analytics/entities/top", params={
            "from": "2026-01-01", "to": "2026-01-31", "entity_type": "ORG"
        })
    
    @task(1)
    def sentiment_dynamics(self):
        self.client.get("/analytics/sentiment/dynamics", params={
            "from": "2026-01-01", "to": "2026-01-31", "bucket": "day"
        })
```

---

### 13. Тесты безопасности

| Категория | Тест-кейсы |
|-----------|-----------|
| SQL Injection | Параметры `from`, `channel`, `topic` с SQL-инъекцией → безопасная обработка |
| XSS | Текст сообщения с `<script>` → экранирование в UI |
| JWT Tampering | Изменённый token → 401, token без signature → 401 |
| CORS | Запрос с неразрешённого origin → блокировка |
| Rate Limiting | > N запросов/мин → 429 Too Many Requests |
| Password Policy | Слабый пароль при регистрации → 422 |
| Token Expiry | Expired access token → 401, refresh → новый access |
| Admin Access | Обычный пользователь → `/admin/*` → 403 |
| CSRF | POST без CSRF-токена (если применимо) → 403 |

---

## Пирамида тестирования

```
         ╱╲
        ╱  ╲        E2E (Playwright, Smoke Scripts)
       ╱    ╲       ← Полный pipeline, браузерные сценарии
      ╱──────╲
     ╱        ╲     Integration (testcontainers, Docker)
    ╱          ╲    ← Kafka round-trip, DB persist, API ↔ DB
   ╱────────────╲
  ╱              ╲  Unit (pytest, Jest)
 ╱                ╲ ← Чистая бизнес-логика, утилиты, модели
╱──────────────────╲
```

| Уровень | Количество | Скорость | Цена поддержки |
|---------|-----------|----------|----------------|
| Unit | Много (≥ 80% покрытия) | Секунды | Низкая |
| Integration | Среднее | Десятки секунд | Средняя |
| E2E | Мало (критические пути) | Минуты | Высокая |

---

## Матрица покрытия по сервисам

| Сервис | Unit | Integration | Smoke | E2E | Статус |
|--------|:----:|:-----------:|:-----:|:---:|--------|
| **Frontend (Jest)** | ✅ | — | — | ✅ | Частично реализовано |
| **Auth Service** | ❌ | ❌ | — | ✅ (через Playwright) | Только E2E |
| **Message Persister** | ❌ | ❌ | — | — | Нет тестов |
| **Preprocessor** | ❌ | ❌ | ✅ (bash) | — | Только smoke |
| **Sentiment Analyzer** | ❌ | ❌ | — | — | Нет тестов |
| **NER Extractor** | ❌ | ❌ | — | — | Нет тестов |
| **Topic Clusterer** | ❌ | ❌ | — | — | Нет тестов |
| **Collector** | ❌ | ❌ | — | — | Нет тестов |
| **Инфраструктура** | — | — | ✅ (ps1) | — | PowerShell smoke |
| **JSON Schemas** | — | ✅ (в smoke) | — | — | Валидация в smoke |

---

## Команды запуска

### Все Backend-тесты

```bash
# Будущие тесты сервисов (после создания)
pytest auth_service/tests/ -v
pytest message_persister/tests/ -v
pytest preprocessor/tests/ -v
```

### Frontend Unit-тесты

```bash
cd frontend
npm test                  # Jest — все unit-тесты
npm test -- --coverage    # С отчётом покрытия
```

### Frontend E2E-тесты

```bash
cd frontend
npx playwright install          # Установка браузеров (один раз)
npx playwright test             # Запуск всех E2E
npx playwright test --ui        # Интерактивный режим
npx playwright show-report      # Просмотр HTML-отчёта
```

### Инфраструктурный Smoke

```powershell
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts/smoke_test.ps1
```

### Preprocessor Smoke

```bash
bash preprocessor/scripts/smoke_test.sh
```

---

## Рекомендуемая структура каталогов для тестов

```
Tg_news_project/
├── tests/
│   ├── smoke/
│   ├── contracts/
│   │   └── test_schemas.py              ⬜ планируется
│   ├── load/
│   │   └── locustfile.py                ⬜ планируется
│   └── security/
│       └── test_auth_security.py        ⬜ планируется
│
├── auth_service/
│   └── tests/
│       ├── conftest.py                  ⬜ планируется
│       ├── test_auth.py                 ⬜ планируется
│       ├── test_jwt.py                  ⬜ планируется
│       ├── test_admin.py                ⬜ планируется
│       └── test_email.py                ⬜ планируется
│
├── message_persister/
│   └── tests/
│       ├── conftest.py                  ⬜ планируется
│       ├── test_persister.py            ⬜ планируется
│       └── test_idempotency.py          ⬜ планируется
│
├── preprocessor/
│   ├── scripts/smoke_test.sh            ✅ реализовано
│   └── tests/
│       ├── test_normalize.py            ⬜ планируется
│       └── test_tokenize.py             ⬜ планируется
│
├── sentiment_analyzer/
│   └── tests/
│       ├── test_model.py                ⬜ планируется
│       └── test_inference.py            ⬜ планируется
│
├── ner_extractor/
│   └── tests/
│       ├── test_pipeline.py             ⬜ планируется
│       └── test_extraction.py           ⬜ планируется
│
├── topic_clusterer/
│   └── tests/
│       ├── test_embeddings.py           ⬜ планируется
│       └── test_clustering.py           ⬜ планируется
│
├── rbc_telegram_collector/
│   └── tests/
│       ├── test_config.py               ⬜ планируется
│       ├── test_models.py               ⬜ планируется
│       ├── test_sinks.py                ⬜ планируется
│       └── test_state.py                ⬜ планируется
│
├── frontend/
│   ├── src/__tests__/
│   │   ├── auth.test.ts                 ✅ реализовано
│   │   └── utils.test.ts                ✅ реализовано
│   └── e2e/
│       └── auth.spec.ts                 ✅ реализовано
│
└── scripts/
    └── smoke_test.ps1                   ✅ реализовано
```

---

## CI/CD (план)

На данный момент CI/CD отсутствует. Рекомендуемый pipeline (GitHub Actions):

```yaml
# .github/workflows/test.yml
name: Test Suite
on: [push, pull_request]

jobs:
  backend-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install pytest pytest-asyncio
      - run: pytest tests/ -v

  frontend-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - run: cd frontend && npm ci && npm test -- --ci

  frontend-e2e:
    runs-on: ubuntu-latest
    needs: [frontend-unit]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - run: cd frontend && npm ci && npx playwright install --with-deps
      - run: cd frontend && npx playwright test

  schema-validation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install jsonschema
      - run: python -c "..." # validate schemas + examples
```

---

## Приоритеты реализации

| Приоритет | Задача | Обоснование |
|-----------|--------|-------------|
| 🔴 P0 | Unit-тесты Auth Service | Критичный для безопасности; JWT, пароли, rate-limiting |
| 🔴 P0 | Контрактные тесты JSON Schema | Гарантия совместимости между сервисами |
| 🟠 P1 | Unit-тесты Message Persister | Идемпотентность — ключевое свойство pipeline |
| 🟠 P1 | Unit-тесты Preprocessor | Нормализация текста влияет на все downstream-сервисы |
| 🟡 P2 | Unit-тесты Sentiment Analyzer | ML-inference корректность |
| 🟡 P2 | Unit-тесты NER Extractor | Извлечение сущностей — core value |
| 🟡 P2 | Расширенные E2E (Playwright) | Покрытие основных user journeys |
| 🟢 P3 | Unit-тесты Topic Clusterer | Кластеризация менее критична |
| 🟢 P3 | Unit-тесты Collector | Сбор данных — edge сервис |
| 🟢 P3 | Нагрузочное тестирование | Важно перед production-нагрузкой |
| 🟢 P3 | CI/CD GitHub Actions | Автоматизация регрессионного тестирования |
| 🔵 P4 | Тесты безопасности | Углублённый security audit |
