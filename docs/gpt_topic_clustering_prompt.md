# Prompt: GPT Topic Clustering For Telegram News

Ты получишь JSONL-файл. Каждая строка - отдельное сообщение Telegram с `event_id`, `channel`, `message_id`, датой, текстом, sentiment, aspects и уже найденными entities.

Задача: сгруппировать все входные сообщения в смысловые новостные темы так, чтобы результат можно было загрузить в таблицы `cluster_runs_pg` и `cluster_assignments`.

Верни только JSONL, без Markdown и без пояснений. Одна выходная строка должна соответствовать одной входной строке.

## Цель кластеризации

Кластер - это одна новостная тема/сюжет, а не просто общая рубрика. Например:

- `Иран и переговоры с США`
- `Блокировки банковских счетов`
- `Рынок нефти и санкции`
- `Задержание руководства Эксмо`
- `Регулирование вакцин и здравоохранение`

Не объединяй слишком широко. `политика`, `экономика`, `война`, `общество` - слишком широкие кластеры. Но и не создавай отдельный кластер для каждого сообщения, если сообщения явно про один сюжет.

## Правила

1. Сохрани все входные строки: для каждого входного `request_id` верни ровно одну выходную строку.
2. Сохраняй без изменений: `request_id`, `event_id`, `channel`, `message_id`, `raw_message_id`, `preprocessed_message_id`.
3. `run_id` для всех строк должен быть одинаковым: `gpt_topics_2026_04_21_v1`.
4. `cluster_id` должен быть целым числом `0..N-1`.
5. Не используй `cluster_id=-1`, кроме полностью непонятных/мусорных сообщений. Если сообщение содержательное, назначь его в ближайшую тему.
6. `public_cluster_id` должен быть строкой `gpt_topics_2026_04_21_v1:<cluster_id>`.
7. `topic_label` - короткое название темы, 2-7 слов, UTF-8, без mojibake. Для русских сообщений используй нормальную кириллицу, не `Р...`.
8. `topic_summary` - одно короткое предложение о теме.
9. `cluster_probability` - уверенность назначения сообщения к теме:
   - `0.90-1.00` явное совпадение с темой;
   - `0.70-0.89` тема подходит, но текст частично боковой;
   - `0.50-0.69` слабое совпадение;
   - ниже `0.50` только для мусора или очень коротких сообщений.
10. `topic_keywords` - 3-8 ключевых слов/фраз.
11. `primary_entities` - максимум 6 ключевых сущностей темы. Используй типы `PERSON`, `ORG`, `GPE`, `LOC`, `PRODUCT`, `EVENT`.
12. `event_type` один из: `policy`, `markets`, `company`, `conflict`, `crime`, `technology`, `public_health`, `society`, `media`, `other`.
13. `bucket_id` ставь по дате сообщения в формате `YYYY-MM-DD`.
14. Не добавляй полей вне схемы ниже.

## Выходная JSONL-схема

Каждая строка:

```json
{
  "request_id": "topic_src_0001",
  "event_id": "channel:123",
  "channel": "channel",
  "message_id": 123,
  "raw_message_id": "uuid",
  "preprocessed_message_id": "uuid",
  "run_id": "gpt_topics_2026_04_21_v1",
  "cluster_id": 0,
  "public_cluster_id": "gpt_topics_2026_04_21_v1:0",
  "cluster_probability": 0.95,
  "bucket_id": "2026-04-21",
  "topic_label": "короткое название темы",
  "topic_summary": "одно короткое предложение",
  "topic_keywords": ["keyword1", "keyword2", "keyword3"],
  "primary_entities": [
    {
      "text": "string",
      "type": "PERSON|ORG|GPE|LOC|PRODUCT|EVENT",
      "normalized": "string"
    }
  ],
  "event_type": "policy|markets|company|conflict|crime|technology|public_health|society|media|other"
}
```

## Критерии качества

- Количество кластеров для 339 сообщений ожидаемо примерно `20-60`.
- В кластере обычно должно быть от 2 до 30 сообщений.
- Допустимы кластеры из 1 сообщения только для уникальных важных сюжетов.
- Сообщения из разных каналов про один сюжет должны попадать в один кластер.
- Повторы, дайджесты и краткие новости группируй по конкретному сюжету, если он понятен.
- Если сообщение - дайджест с несколькими новостями, кластеризуй по самой заметной/первой новости или по общему типу `daily_digest`, если невозможно выделить один сюжет.

## Последующий импорт в БД

После твоего ответа оператор загрузит данные так:

- `run_id` -> `cluster_runs_pg.run_id`
- уникальные `cluster_id` -> `cluster_runs_pg.n_clusters`
- `event_id`, `channel`, `message_id`, `raw_message_id`, `preprocessed_message_id`, `cluster_id`, `cluster_probability`, `bucket_id` -> `cluster_assignments`
- `public_cluster_id` будет вычислен БД как `run_id || ':' || cluster_id`

Поля `topic_label`, `topic_summary`, `topic_keywords`, `primary_entities`, `event_type` нужны для проверки качества и возможной staging-таблицы. Не искажай кириллицу.
