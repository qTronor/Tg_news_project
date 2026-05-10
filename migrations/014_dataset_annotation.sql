-- Migration: 014_dataset_annotation
-- Description: Dataset versioning and manual annotation system for Topic Modeling benchmarks
-- Date: 2026-05-02

-- ─── Dataset version registry ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dataset_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL UNIQUE,          -- e.g. ru-telegram-topics-v1
    description TEXT,
    language VARCHAR(10) NOT NULL DEFAULT 'ru',
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    channels TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    min_word_count INTEGER NOT NULL DEFAULT 5,
    dedup_strategy VARCHAR(40) NOT NULL DEFAULT 'event_id', -- event_id | text_hash | none
    total_items INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(40) NOT NULL DEFAULT 'building',         -- building | ready | archived
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID,                                        -- references auth.users.id (app-enforced)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT dataset_versions_window_check CHECK (window_end > window_start),
    CONSTRAINT dataset_versions_status_check
        CHECK (status IN ('building', 'ready', 'archived')),
    CONSTRAINT dataset_versions_dedup_check
        CHECK (dedup_strategy IN ('event_id', 'text_hash', 'none'))
);

-- ─── Individual messages selected for a dataset ──────────────────────────────

CREATE TABLE IF NOT EXISTS dataset_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_version_id UUID NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE,
    event_id VARCHAR(512) NOT NULL,
    channel VARCHAR(255) NOT NULL,
    message_id BIGINT NOT NULL,
    text TEXT NOT NULL,
    cleaned_text TEXT,
    message_date TIMESTAMPTZ NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    language VARCHAR(10),
    split VARCHAR(40) NOT NULL DEFAULT 'unassigned', -- train | validation | test | temporal_test | unassigned
    cluster_id VARCHAR(255),                          -- cluster assignment at build time
    auto_topic_label VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT dataset_items_split_check
        CHECK (split IN ('train', 'validation', 'test', 'temporal_test', 'unassigned')),
    CONSTRAINT dataset_items_unique UNIQUE (dataset_version_id, event_id)
);

-- ─── Annotators ──────────────────────────────────────────────────────────────
-- user_id references tg_news_auth.users.id — cross-DB FK enforced at app layer

CREATE TABLE IF NOT EXISTS annotators (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE,
    username VARCHAR(255) NOT NULL UNIQUE,
    role VARCHAR(40) NOT NULL DEFAULT 'annotator', -- annotator | lead | admin
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    annotation_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT annotators_role_check CHECK (role IN ('annotator', 'lead', 'admin'))
);

-- ─── Annotation tasks (one per item; multiple per item = IAA mode) ────────────

CREATE TABLE IF NOT EXISTS annotation_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_item_id UUID NOT NULL REFERENCES dataset_items(id) ON DELETE CASCADE,
    annotator_id UUID REFERENCES annotators(id) ON DELETE SET NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'pending', -- pending | in_progress | completed | skipped
    priority INTEGER NOT NULL DEFAULT 0,
    assigned_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT annotation_tasks_status_check
        CHECK (status IN ('pending', 'in_progress', 'completed', 'skipped'))
);

-- ─── Annotation labels ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS annotation_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES annotation_tasks(id) ON DELETE CASCADE,
    annotator_id UUID NOT NULL REFERENCES annotators(id) ON DELETE CASCADE,
    -- Broad topic
    broad_topic VARCHAR(255),
    broad_topic_confidence REAL,
    -- Specific storyline / event
    storyline VARCHAR(512),
    is_new_storyline BOOLEAN,
    -- Quality label
    quality VARCHAR(40) NOT NULL DEFAULT 'useful', -- useful | noise | duplicate
    -- Manually corrected entities: [{text, type}]
    entities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Annotator notes
    comment TEXT,
    -- Overall annotation confidence 0–1
    annotator_confidence REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT annotation_labels_quality_check
        CHECK (quality IN ('useful', 'noise', 'duplicate')),
    CONSTRAINT annotation_labels_confidence_check
        CHECK (annotator_confidence IS NULL
               OR (annotator_confidence >= 0 AND annotator_confidence <= 1)),
    -- One label per annotator per task (upsert-safe)
    CONSTRAINT annotation_labels_task_annotator_unique UNIQUE (task_id, annotator_id)
);

-- ─── Annotation guidelines (versioned Markdown) ──────────────────────────────

CREATE TABLE IF NOT EXISTS annotation_guidelines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version VARCHAR(40) NOT NULL UNIQUE,  -- e.g. v1.0
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,                -- Markdown
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Dataset splits ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dataset_splits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_version_id UUID NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE,
    split_name VARCHAR(40) NOT NULL,      -- train | validation | test | temporal_test
    item_count INTEGER NOT NULL DEFAULT 0,
    ratio REAL,                           -- fraction of total
    start_date TIMESTAMPTZ,              -- for temporal splits
    end_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT dataset_splits_unique UNIQUE (dataset_version_id, split_name),
    CONSTRAINT dataset_splits_name_check
        CHECK (split_name IN ('train', 'validation', 'test', 'temporal_test'))
);

-- ─── Indexes ─────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_dataset_items_version
    ON dataset_items(dataset_version_id, split, created_at);
CREATE INDEX IF NOT EXISTS idx_dataset_items_event
    ON dataset_items(event_id);
CREATE INDEX IF NOT EXISTS idx_dataset_items_channel_date
    ON dataset_items(channel, message_date);

CREATE INDEX IF NOT EXISTS idx_annotation_tasks_status
    ON annotation_tasks(status, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_annotation_tasks_annotator
    ON annotation_tasks(annotator_id, status);
CREATE INDEX IF NOT EXISTS idx_annotation_tasks_item
    ON annotation_tasks(dataset_item_id);

CREATE INDEX IF NOT EXISTS idx_annotation_labels_task
    ON annotation_labels(task_id);
CREATE INDEX IF NOT EXISTS idx_annotation_labels_annotator
    ON annotation_labels(annotator_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dataset_versions_status
    ON dataset_versions(status, created_at DESC);

-- ─── Seed active guideline v1.0 ──────────────────────────────────────────────

INSERT INTO annotation_guidelines (version, title, content, is_active)
VALUES (
    'v1.0',
    'Правила разметки тем (v1.0)',
    '# Правила разметки тем Telegram-новостей

## Структура разметки

Каждое сообщение размечается по пяти измерениям:

1. **Крупная тема** — категория верхнего уровня (Политика, Экономика, …)
2. **Конкретный сюжет/событие** — что именно происходит
3. **Новая тема или продолжение** — первый раз эта тема появляется или нет
4. **Сущности** — ключевые персоны, организации, места
5. **Качество сообщения** — полезное, шум или дубль

---

## Крупные темы

| Код | Тема |
|-----|------|
| Политика | Выборы, законы, деятельность государственных органов, партий |
| Экономика | Финансы, рынки, бизнес, цены, ставки ЦБ |
| Общество | Социальные события, права человека, демография |
| Безопасность | Война, конфликты, теракты, криминал |
| Международные отношения | Дипломатия, санкции, переговоры |
| Технологии | IT, ИИ, наука, инновации |
| Здоровье | Медицина, эпидемии, фармацевтика |
| Культура | Искусство, спорт, образование, СМИ |
| Другое | Не подходит ни под одну категорию |

---

## Сюжет vs тема

- **Тема** — широкая категория (Политика, Экономика)
- **Сюжет** — конкретное событие или история в рамках темы

**Примеры:**
- Тема: Экономика → Сюжет: «Повышение ключевой ставки ЦБ до 21%»
- Тема: Безопасность → Сюжет: «Обмен военнопленными — март 2025»

Один сюжет может продолжаться неделями. Несколько сообщений об одном событии → один сюжет.

---

## Новая тема или продолжение

- **Новая** — вы не видели этот сюжет в предыдущих сообщениях
- **Продолжение** — тема уже встречалась; это обновление или развитие

Если сомневаетесь, укажите «Продолжение».

---

## Качество сообщений

### Полезное
- Несёт новую информацию
- Минимальный объём: ≥ 5 слов осмысленного текста
- Не является точной копией другого сообщения

### Шум
- Реклама, спам, опросы без контекста
- Только ссылка без пояснительного текста
- Технические сообщения (бот, системные уведомления)
- Менее 5 слов осмысленного текста

### Дубль
- Почти дословное повторение другого сообщения
- Репост без добавленной информации
- Одно и то же событие, одни и те же факты, другой канал

---

## Неоднозначные случаи

- **Пересечение тем**: выберите доминирующую
- **Без текста**: только картинка / видео → «Шум»
- **Мнение без фактов**: засчитывайте как «Полезное», тема — «Общество» или «Политика»
- **Репост с комментарием**: «Полезное», если комментарий добавляет что-то новое

---

## Сущности

Исправляйте только **явные ошибки** автоматического NER. Типы:
- **PER** — персоны (Путин, Набиуллина)
- **ORG** — организации (ЦБ, Сбербанк, ООН)
- **LOC** — места (Москва, Украина, Ближний Восток)
- **MISC** — прочие (названия законов, событий)

---

## Уверенность разметчика

- **1.0** — полная уверенность
- **0.7–0.9** — небольшие сомнения
- **0.5–0.7** — серьёзные сомнения, тема неоднозначная
- **< 0.5** — очень сложный случай, нужна проверка

---

## Inter-Annotator Agreement (IAA)

Часть задач назначается нескольким разметчикам. Это нормально — расхождения анализируются через Cohen''s κ. Если κ < 0.6, задачи пересматриваются через сессию калибровки.
',
    TRUE
) ON CONFLICT (version) DO NOTHING;

DO $$
BEGIN
    RAISE NOTICE 'Migration 014_dataset_annotation completed successfully';
END $$;
