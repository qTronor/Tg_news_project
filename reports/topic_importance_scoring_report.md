# Отчёт: Слой ранжирования важности тем (Topic Importance Scoring)

## 1. Постановка задачи

В системе анализа Telegram-новостей кластеризация уже обнаруживает темы,
но все темы отображаются без приоритизации. Цель данного слоя — вычислить
`importance_score` для каждого кластера и сделать ранжирование объяснимым,
чтобы пользователь понимал, **почему** тема выделена как важная.

Ограничения:
- Нельзя использовать LLM.
- Решение должно быть детерминированным и воспроизводимым.
- Нельзя изменять логику кластеризации.

---

## 2. Принятые решения

### 2.1 Отдельный сервис, не встроенный в кластеризатор

`topic_scorer` — самостоятельный контейнер, который читает результаты
кластеризации из PostgreSQL и записывает в отдельную таблицу `topic_scores`.
Это позволяет:
- менять формулу без перезапуска кластеризатора;
- хранить историю пересчётов;
- тестировать в изоляции.

### 2.2 Сигналы для scoring

Выбраны сигналы, которые уже присутствуют в БД без дополнительных затрат:

| Сигнал | Обоснование |
|---|---|
| Скорость роста (`growth_rate`) | Самый сильный предиктор breaking news |
| Охват каналов (`unique_channels`) | Широко распространившаяся тема важнее |
| Объём (`message_count`) | Baseline популярности |
| Доля новых каналов | Новые источники = новая аудитория |
| Уникальные сущности | Более насыщенная тема = выше значимость |
| Новизна сущностей | Новые имена/организации → потенциально важное событие |
| Тональная интенсивность | Сильный негатив часто сигнализирует о кризисе |
| Тональный сдвиг | Резкая смена тональности — маркер развития события |
| Плотность графа | Плотная связность = больше подтверждений темы |

### 2.3 Нормализация per-run, а не глобальная

Min-max нормализация вычисляется по всем кластерам текущего run,
а не по глобальной истории. Это делает score относительным внутри run
(«самая важная тема из сегодняшних»), что естественнее для пользователя
и устойчивее к дрейфу данных.

### 2.4 Penalty за малые кластеры

Кластеры с `message_count < 3` получают `penalty_factor = 0.5`.
Без этого маленький кластер с нулевым prev_count получал `growth_rate = +∞`
(→ clip 5.0) и мог опережать реальные темы.

### 2.5 История пересчётов

Каждый вызов скоринга вставляет **новую** строку (не обновляет старую).
Это позволяет отслеживать, как importance темы менялся во времени.
Для API используется view `topic_scores_latest`, которая возвращает
только самую свежую строку на кластер.

---

## 3. Формула

```
raw_i    = compute_raw_features(cluster)   # специфично для каждой фичи
norm_i   = (raw_i - run_min_i) / (run_max_i - run_min_i)  # per-run min-max
score    = Σ (norm_i × w_i) × penalty_factor
```

### Дефолтные веса

```yaml
growth_rate:        0.22   # самый сильный сигнал breaking news
unique_channels:    0.14   # охват
message_count:      0.12   # объём
novelty:            0.10   # новые сущности
unique_entities:    0.10   # насыщенность
sentiment_intensity: 0.10  # тональная сила
new_channel_ratio:  0.08   # новые источники
cluster_density:    0.08   # граф
sentiment_shift:    0.06   # тональный перелом
```

Сумма весов = 1.0.

### Уровни важности

```
[0.00, 0.35) → low
[0.35, 0.65) → medium
[0.65, 0.85) → high
[0.85, 1.00] → critical
```

---

## 4. Реализованные компоненты

### Файловая структура

```
topic_scorer/
├── Dockerfile
├── docker-compose.yml
├── config.example.yaml
├── requirements.txt
├── main.py
└── topic_scorer/
    ├── __init__.py
    ├── cli.py               # Аргументы: batch | oneshot | scheduled
    ├── config.py            # Pydantic + YAML + ENV overrides
    ├── features.py          # compute_raw_features, normalize_features, compute_per_run_stats
    ├── logging_utils.py
    ├── metrics.py           # Prometheus counters/histograms
    ├── repository.py        # Все SQL: чтение фич + запись оценок
    ├── schemas.py           # ClusterFeatures, ComponentScore, ScoreBreakdown, TopicScore
    └── service.py           # Orchestration: batch / oneshot / scheduled
```

### База данных

Миграция `009_topic_importance_scoring.sql`:
- Таблица `topic_scores` — результаты с историей
- View `topic_scores_latest` — DISTINCT ON по cluster_id
- Таблица `topic_scoring_runs` — аудит-лог запусков

### Analytics API

Обновлён `analytics_api/analytics_api/service.py`:
- `GET /analytics/overview/clusters` — новые поля `importance_score`, `importance_level`, `score_calculated_at`; query params `sort_by`, `min_importance`, `importance_level`
- `GET /analytics/clusters/{clusterId}` — полный `score_breakdown` JSON

### Тесты

```
tests/unit/
├── test_topic_scorer_features.py    # 16 unit-тестов: raw features, нормализация, edge cases
├── test_topic_scorer_scoring.py     # 16 unit-тестов: монотонность, пенальти, уровни, конфиг
└── test_topic_scorer_regression.py  # 8 regression-тестов: 5 golden кластеров, детерминированность

tests/integration/
└── test_topic_scorer_pg.py          # 3 integration-теста (требуется TEST_DATABASE_DSN)
```

---

## 5. Запуск

```bash
# Разовый пересчёт последнего run
docker compose -f topic_scorer/docker-compose.yml run topic-scorer-batch

# Постоянный процесс с интервалом 5 мин
docker compose -f topic_scorer/docker-compose.yml up -d topic-scorer

# Unit-тесты (не нужна БД)
cd /project && python -m pytest tests/unit/test_topic_scorer_*.py -v

# Integration-тесты
TEST_DATABASE_DSN=postgresql://... python -m pytest tests/integration/test_topic_scorer_pg.py -v
```

---

## 6. Интеграция в Frontend

### Сортировка по важности
```
GET /analytics/overview/clusters?sort_by=importance
```

### Фильтрация только важных тем
```
GET /analytics/overview/clusters?importance_level=high,critical
```

### Панель объяснимости ("Почему тема важна?")
```
GET /analytics/clusters/{clusterId}
→ score_breakdown.components → отрисовать bar chart вкладов компонент
```

Пример UI-текста для `critical`-темы:
> "Эта тема важна прежде всего из-за высокой скорости роста (+210% за последние 3 часа)
> и широкого охвата каналов (18 уникальных источников, из которых 10 новые)."

---

## 7. Конфигурирование и версионирование

При изменении весов нужно увеличить `scoring.version` в config:
```yaml
scoring:
  version: "v2"
```

Все новые строки будут иметь `scoring_version=v2`.
Старые строки с `v1` сохраняются в истории для сравнения.

---

## 8. Trade-offs

| Решение | Альтернатива | Обоснование выбора |
|---|---|---|
| Per-run нормализация | Глобальная нормализация | Относительный ранг внутри run естественнее; нет дрейфа от исторических экстремумов |
| Взвешенная сумма | Random Forest / XGBoost | Детерминированность, объяснимость, диплом-совместимость |
| Min-max | Z-score | Min-max всегда в [0,1], безопаснее для суммирования |
| История + view | Обновление на месте | История пересчётов для анализа тренда importance |
| Отдельный сервис | Встроен в clusterer | Независимое развёртывание, тестирование, масштабирование |
