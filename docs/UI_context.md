## Контекст проекта

Я работаю над ВКР: «Веб-приложение для кластерного анализа новостей из Telegram и анализа графа сущностей новостного потока».

Репозиторий: `c:\Users\roman\OneDrive\Desktop\Tg_news_project`

### Git-ветки
- `main` — бэкенд микросервисы (message_persister, preprocessor, sentiment_analyzer, ner_extractor, topic_clusterer, analytics_duckdb)
- `feature/frontend-ui` — фронтенд Next.js (закоммичен)
- `feature/auth-system` (текущая) — система аутентификации, профили пользователей, i18n (НЕ закоммичена, нужно закоммитить)

---

## Бэкенд (main ветка)

Микросервисная event-driven архитектура на Python + Kafka + PostgreSQL + Neo4j + DuckDB:

- **message_persister** — сохраняет сырые сообщения из Telegram в PostgreSQL
- **preprocessor** — очистка/нормализация текста
- **sentiment_analyzer** — тональность (RuBERT), пишет в Kafka `sentiment.enriched`
- **ner_extractor** — извлечение сущностей (Natasha NER), пишет в Kafka `ner.enriched`
- **topic_clusterer** — эмбеддинги (SBERT) + UMAP + HDBSCAN → кластеры в DuckDB
- **analytics_duckdb** — REST API на порту 8020 для UI, читает из Parquet lake

### API endpoints (analytics_duckdb, порт 8020):
- `GET /analytics/overview/clusters` — обзор кластеров
- `GET /analytics/entities/top` — топ сущностей
- `GET /analytics/sentiment/dynamics` — динамика тональности
- `GET /analytics/clusters/{cluster_id}/documents` — сообщения в кластере
- `GET /analytics/clusters/{cluster_id}/related` — связанные кластеры

### Kafka topics:
raw.telegram.messages → persisted.messages → preprocessed.messages → sentiment.enriched / ner.enriched

### Планируемые, но ещё не реализованные компоненты:
- graph-builder (sentiment.enriched + ner.enriched → graph.updates)
- neo4j-writer (graph.updates → Neo4j)

---

## Auth Service (ветка feature/auth-system)

FastAPI микросервис на порту 8030 (`auth_service/`):

**Стек:** FastAPI + SQLAlchemy (async) + asyncpg + python-jose (JWT) + passlib (bcrypt) + slowapi (rate limiting) + aiosmtplib (email)

**Базa данных:** `tg_news_auth` — отдельная БД в том же PostgreSQL-контейнере (`telegram-news-postgres`), что и основная `telegram_news`. PII изолированы от аналитических данных.

**Таблицы (5 штук):**
- `users` (id UUID, email, username, password_hash bcrypt-12, role admin/user, is_active, **email_verified**, timestamps)
- `refresh_sessions` (id, user_id, refresh_token_hash SHA-256, expires_at, ip, ua)
- `admin_audit_log` (id, admin_id, action, target_type/id, old_value/new_value JSONB, ip, ua, created_at)
- `message_reactions` (id, user_id, message_event_id, reaction like/dislike, UNIQUE user+message)
- `channel_visibility` (id, channel_name UNIQUE, is_visible, updated_by)

**API endpoints (порт 8030):**
- `POST /api/auth/register` — регистрация, возвращает JWT пару + отправляет verification email
- `POST /api/auth/login` — вход по email или username, возвращает JWT пару
- `POST /api/auth/refresh` — ротация токенов
- `POST /api/auth/logout` — инвалидация refresh token
- `GET /PUT /api/auth/me` — профиль (включает email_verified)
- `POST /api/auth/change-password`
- `POST /api/auth/forgot-password` — отправляет email со ссылкой на сброс пароля
- `POST /api/auth/reset-password` — устанавливает новый пароль по токену
- `POST /api/auth/verify-email` — подтверждает email по токену
- `POST /api/auth/resend-verification` — повторно отправляет email верификации
- `PATCH /api/admin/messages/{event_id}` — админ правит sentiment/topic/entities + audit log
- `GET /PUT /api/admin/channels/{name}` — видимость каналов + audit
- `GET /api/admin/audit-log` — пагинированный журнал аудита
- `POST /api/messages/{event_id}/reaction` — toggle like/dislike
- `GET /api/messages/{event_id}/reactions` — счётчики + реакция текущего юзера
- `POST /api/messages/batch-reactions` — batch для ленты

**Безопасность:**
- JWT access (30 мин) + refresh (30 дней), ротация при refresh
- bcrypt 12 раундов, SHA-256 для refresh tokens
- Rate limiting (slowapi, 30 req/min)
- Security headers middleware (X-Frame-Options DENY, nosniff, no-cache)
- RBAC через FastAPI Depends (get_current_user, require_admin)
- CORS ограничен на localhost:3000

**Bootstrap admin:** создаётся при первом запуске из env-переменных ADMIN_EMAIL / ADMIN_PASSWORD.

**Файловая структура auth_service/:**
```
auth_service/
├── app/
│   ├── __init__.py
│   ├── main.py          — FastAPI app, lifespan, middleware, routers
│   ├── config.py        — pydantic-settings, env prefix AUTH_
│   ├── database.py      — async engine, sessionmaker, Base
│   ├── models.py        — SQLAlchemy models (5 таблиц)
│   ├── schemas.py       — Pydantic request/response schemas
│   ├── security.py      — hash_password, verify, create_access/refresh_token, decode, email_verify/reset tokens
│   ├── email.py         — send_verification_email, send_password_reset_email (aiosmtplib)
│   ├── dependencies.py  — get_current_user, require_admin, get_client_ip
│   └── routes/
│       ├── __init__.py
│       ├── auth.py      — register, login, refresh, logout, me, change-password, forgot/reset-password, verify-email
│       ├── admin.py     — edit_message, channels CRUD, audit-log
│       └── reactions.py — add/get/batch reactions
├── alembic/             — миграции (env.py, script.py.mako)
├── alembic.ini
├── requirements.txt
├── Dockerfile
├── docker-compose.yml   — standalone dev-only (без отдельного PG)
└── config.example.env
```

---

## Фронтенд (ветка feature/auth-system)

**Стек:** Next.js 16 (App Router) + TypeScript + Tailwind CSS v4 + Recharts + Cytoscape.js + Framer Motion + TanStack Query + next-themes + jose + Jest + Playwright

### Файловая структура frontend/src/:

**Страницы (14 маршрутов):**
- `/` — Dashboard: KPI-карточки, sentiment area chart, top entities, top topics, channel bar chart
- `/login` — Страница входа/регистрации (без sidebar), animated, с toggle между режимами + ссылка «Забыли пароль?»
- `/forgot-password` — Запрос сброса пароля (email форма, standalone без sidebar)
- `/reset-password` — Установка нового пароля по токену из URL (?token=...)
- `/feed` — Лента сообщений с фильтрами + Live mode + like/dislike + admin edit
- `/topics` — Список тем (grid/list) с sparklines
- `/topics/[clusterId]` — Детали кластера: volume, channels, sentiment donut, entities, related
- `/entities` — Таблица сущностей с фильтрами по типу PER/ORG/LOC/MISC
- `/entities/[entityId]` — Профиль сущности: stats, related topics, recent mentions
- `/graph` — Интерактивный граф (Cytoscape.js) с фильтрами
- `/settings` — API URL, polling, channels, demo/live, theme, notifications
- `/admin/channels` — (admin only) Управление видимостью каналов
- `/admin/audit-log` — (admin only) Журнал аудита действий администраторов

**Ключевые компоненты:**
- `components/providers.tsx` — QueryClient, ThemeProvider, I18nContext, AuthProvider, DemoContext, TimeRangeContext
- `components/auth/auth-provider.tsx` — AuthContext (user, isAdmin, login, register, logout), автоматический redirect на /login, обработка auth:logout event
- `components/layout/sidebar.tsx` — Анимированный sidebar, role-based, **мобильный drawer** (slide-in overlay на <md), кнопка закрытия
- `components/layout/header.tsx` — **Hamburger-меню** (md:hidden), time range presets (hidden <sm), Demo/Live, язык, тема, user dropdown. Responsive toolbar
- `components/layout/app-shell.tsx` — SidebarContext + mobileOpen, скрывает sidebar на /login, /forgot-password, /reset-password. Overlay при мобильном sidebar
- `components/admin/message-edit-modal.tsx` — Модальное окно редактирования sentiment/topic/entities (admin only)
- `components/feed/message-card.tsx` — Карточка сообщения: entity badges, sentiment dot, **like/dislike кнопки**, **admin pencil edit icon**
- `components/graph/graph-view.tsx` — Cytoscape.js wrapper
- `components/charts/` — sentiment-area, channel-bar, volume-line, sentiment-donut (Recharts)
- `components/ui/` — Card, Badge, KpiCard, Sparkline

**Data layer:**
- `lib/api.ts` — API client для analytics_duckdb (fetch + AbortController, 5s timeout)
- `lib/auth.ts` — Auth API client: login, register, logout, getProfile, editMessage, channels, reactions, audit, **forgotPassword, resetPassword, verifyEmail, resendVerification**. JWT управление: localStorage, автоматический refresh до истечения, singleton promise, auth:logout event на 401
- `lib/use-data.ts` — React Query хуки (useOverview, useTopics, useTopicDetail, useEntities, useSentiment, useMessages, useGraph). isDemo=true → mock, isDemo=false → API + polling 15s
- `lib/mock-data.ts` — Реалистичные заглушки: 6 тем, 12 сущностей, ~48 сообщений, граф (русскоязычные данные)
- `lib/config.ts` — apiBaseUrl (8020), authBaseUrl (8030), pollingIntervalMs, appName
- `lib/hooks.ts` — useTimeRange (presets 1h/6h/24h/7d/30d/custom)
- `lib/utils.ts` — cn(), formatNumber(), sentimentColor/Label(), entityTypeColor()
- `lib/i18n.ts` — Двуязычная система (RU/EN): ~140 ключей (добавлены forgot/reset password), createContext, useTranslation hook, getTranslator

**Типы (types/index.ts):**
Message, Entity, Topic, TopicDetail, SentimentPoint, OverviewStats, GraphNode, GraphEdge, GraphData, TimeRange, AppConfig, UserProfile, UserRole, ReactionInfo, AuditLogEntry, ChannelVisibility

**Тема:** CSS-переменные в globals.css для light/dark: --positive, --negative, --neutral-sentiment, --entity-per/org/loc/misc

**Middleware (src/middleware.ts):** CSP headers, X-Frame-Options, X-Content-Type-Options, Permissions-Policy, Referrer-Policy

**next.config.ts:** output: "standalone", poweredByHeader: false, HSTS + security headers

---

## Docker Infrastructure (docker-compose.infrastructure.yml)

Все сервисы в одной сети `telegram-news-network`:

| Контейнер | Образ | Порт | Статус |
|---|---|---|---|
| telegram-news-postgres | postgres:15-alpine | 5432 | healthy |
| telegram-news-frontend | ./frontend (multi-stage) | 3000 | healthy |
| telegram-news-auth | ./auth_service | 8030 | healthy |
| telegram-news-kafka | cp-kafka:7.5.0 | 9092 | healthy |
| telegram-news-kafka-ui | kafka-ui | 8080 | healthy |
| telegram-news-neo4j | neo4j:5.15 | 7474, 7687 | healthy |
| telegram-news-redis | redis:7-alpine | 6379 | healthy |
| telegram-news-zookeeper | cp-zookeeper:7.5.0 | 2181 | healthy |
| message-persister | custom | 8000-8001 | running |
| preprocessor | custom | 8010-8011 | running |

**Базы данных в одном PostgreSQL:**
- `telegram_news` — аналитические данные (raw_messages, preprocessed, sentiment, NER, channels, etc.)
- `tg_news_auth` — пользователи, сессии, реакции, аудит, видимость каналов

**Миграции:**
- `migrations/001_initial_schema.sql` — основная аналитическая схема
- `migrations/002_auth_schema.sql` — auth схема (CREATE DATABASE + таблицы + extensions + triggers)

**.env в корне проекта:**
- DB_PASSWORD=pgSecure2026!
- AUTH_JWT_SECRET=k8sP2mXq7v...
- ADMIN_EMAIL=admin@tgnews.local, ADMIN_PASSWORD=Admin123!
- NEO4J_PASSWORD=neo4jSecure2026!

---

## Текущее состояние

- Ветка `feature/auth-system` — изменения НЕ закоммичены
- Все Docker-контейнеры запущены и healthy
- Frontend доступен на http://localhost:3000
- Auth service доступен на http://localhost:8030
- В БД tg_news_auth есть admin user: admin@tgnews.local / Admin123!
- i18n работает (RU по умолчанию, переключается кнопкой EN/RU в хедере)
- Demo/Live toggle работает
- Все 14 маршрутов компилируются и отдают 200
- **Авторизация работает** — login/register/logout через Docker
- **Responsive** — мобильный sidebar (hamburger + drawer overlay), адаптивный header, прокручиваемая таблица сущностей
- **Сброс пароля** — forgot-password → email → reset-password flow (бэкенд + фронтенд)
- **Email-верификация** — JWT-токен 24ч, отправка при регистрации, resend endpoint
- **Email** — aiosmtplib; если SMTP не настроен, письма логируются в stdout (удобно для разработки)
- **Тесты** — Jest (12 unit-тестов: utils, auth tokens) + Playwright E2E (auth flow, навигация)

---

## Исправленные баги

### [2026-03-05] Не работал вход при запуске UI в Docker

**Проблема:** Пользователи (включая admin) не могли залогиниться, когда UI запущен через Docker. Ошибка не отображалась явно — запросы к auth-сервису просто не доходили.

**Причина:** В `docker-compose.infrastructure.yml` и `frontend/docker-compose.yml` build-args для фронтенда использовали `http://host.docker.internal:8030` в качестве `NEXT_PUBLIC_AUTH_BASE_URL`. Поскольку `NEXT_PUBLIC_*` переменные вшиваются в клиентский JS-бандл при сборке (build-time), браузер пользователя пытался обращаться к `host.docker.internal:8030`. Это DNS-имя работает только **внутри Docker-контейнеров**, но **не резолвится на хостовой машине** (проверено: localhost:8030 отвечает, host.docker.internal:8030 — timeout).

**Исправление:**
- `docker-compose.infrastructure.yml`: `NEXT_PUBLIC_AUTH_BASE_URL` и `NEXT_PUBLIC_API_BASE_URL` заменены на `http://localhost:...`
- `frontend/docker-compose.yml`: аналогичная замена
- Frontend контейнер пересобран (`docker compose up -d --build frontend`)

**Затронутые файлы:**
- `docker-compose.infrastructure.yml` (строки build args фронтенда)
- `frontend/docker-compose.yml` (строки build args)

### [2026-03-05] Responsive design (мобильная адаптация)

- **Sidebar**: скрыт на мобильных (<md), показывается как overlay/drawer по нажатию на hamburger-иконку в header. Кнопка закрытия (X) внутри sidebar. Overlay затемняет фон. Закрывается при навигации.
- **Header**: hamburger-кнопка (Menu) видна только на мобильных. Time presets и Demo/Live toggle скрыты на <sm. Язык и тема скрыты на <md. Заголовок обрезается (truncate).
- **Entities table**: обёрнута в `overflow-x-auto` с `min-w-[640px]` для горизонтальной прокрутки на узких экранах.
- **App Shell**: `marginLeft` основного контента заменён с Framer Motion на CSS `transition-[margin-left]`, на мобильных `ml-0`.
- **globals.css**: исправлена опечатка `--margin-foreground` → `--muted-foreground` в dark теме.

**Затронутые файлы:**
- `frontend/src/components/layout/app-shell.tsx`
- `frontend/src/components/layout/sidebar.tsx`
- `frontend/src/components/layout/header.tsx`
- `frontend/src/app/entities/page.tsx`

### [2026-03-05] Сброс пароля (forgot/reset password)

**Бэкенд (auth_service):**
- `POST /api/auth/forgot-password` — принимает email, отправляет JWT-ссылку (1 час) на сброс. Всегда возвращает 200 (не раскрывает существование аккаунта).
- `POST /api/auth/reset-password` — принимает token + new_password, обновляет пароль.
- Добавлен `email.py` — aiosmtplib отправка (если SMTP не настроен — логирует в stdout).
- Добавлены настройки: `AUTH_SMTP_HOST`, `AUTH_SMTP_PORT`, `AUTH_SMTP_USER`, `AUTH_SMTP_PASSWORD`, `AUTH_SMTP_FROM`, `AUTH_SMTP_TLS`, `AUTH_FRONTEND_URL`.
- Добавлены `create_password_reset_token`, `decode_password_reset_token` в `security.py`.
- Добавлены `ForgotPasswordRequest`, `ResetPasswordRequest` в `schemas.py`.

**Фронтенд:**
- `/forgot-password` — форма запроса сброса с email, сообщение об успехе.
- `/reset-password?token=...` — форма нового пароля + подтверждение, проверка токена.
- Ссылка «Забыли пароль?» на странице `/login`.
- `authApi.forgotPassword()`, `authApi.resetPassword()` в `lib/auth.ts`.
- i18n ключи `forgot.*`, `reset.*` на RU/EN.

### [2026-03-05] Email-верификация при регистрации

**Бэкенд:**
- Колонка `email_verified` (bool, default false) добавлена в `users`.
- При `POST /api/auth/register` — отправляется verification email с JWT-ссылкой (24 часа).
- `POST /api/auth/verify-email` — подтверждает email по токену.
- `POST /api/auth/resend-verification` — повторная отправка (требует авторизации).
- `UserProfile` содержит `email_verified`.

**Затронутые файлы бэкенда:**
- `auth_service/app/models.py`, `schemas.py`, `security.py`, `email.py` (новый), `config.py`, `routes/auth.py`, `requirements.txt`

### [2026-03-05] Тесты (Jest + Playwright)

**Unit-тесты (Jest):**
- `src/__tests__/utils.test.ts` — formatNumber, sentimentColor, sentimentLabel, entityTypeColor (8 тестов)
- `src/__tests__/auth.test.ts` — storeTokens, getStoredTokens, clearTokens (4 теста)
- Команда: `npm test` (12 тестов, все проходят)

**E2E тесты (Playwright):**
- `e2e/auth.spec.ts` — рендеринг login, ошибка неверных кредов, переключение login/register, «Забыли пароль?» ссылка, успешный вход + редирект, навигация по sidebar
- Команда: `npm run test:e2e`

**Конфигурация:**
- `jest.config.js`, `jest.setup.ts`, `playwright.config.ts`
- Скрипты в `package.json`: `test`, `test:watch`, `test:e2e`, `test:e2e:ui`

---

## Что можно улучшить / продолжить

- Закоммитить изменения в feature/auth-system
- Улучшить UX/дизайн отдельных страниц
- Добавить real-time обновления через WebSocket/SSE
- Реализовать graph-builder и neo4j-writer для графа сущностей
- Настроить реальный SMTP (AUTH_SMTP_HOST, AUTH_SMTP_PORT и т.д.) для отправки email
- Расширить E2E тесты (покрытие всех страниц, admin функциональность)
- Ограничить некоторые действия для пользователей с неподтверждённым email
