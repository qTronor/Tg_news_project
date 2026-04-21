# Prompt: Minimal GPT Analysis For Telegram News

Ты анализируешь JSONL-файл с сообщениями Telegram. Каждая входная строка - отдельный JSON-объект. Нужно вернуть только JSONL: одна выходная строка на одну входную строку, без Markdown, без пояснений, без общего резюме.

Цель: получить минимальные результаты, которые можно вставить в таблицу `sentiment_results`, и дополнительное компактное обогащение, пока в проекте временно не работает полный контур sentiment/topic/source analysis.

## Правила

1. Не пропускай строки. Для каждого входного `request_id` верни ровно один JSON-объект.
2. Сохраняй без изменений: `request_id`, `event_id`, `preprocessed_message_id`, `channel`, `message_id`.
3. Анализируй поле `text`. Поля `existing_entities` и `existing_relations` используй как подсказку, но не копируй их слепо.
4. Если текста недостаточно для уверенного анализа, поставь `quality.usable=false`, sentiment `neutral`, score/probability не выше `0.55`, а причину укажи в `quality.reason`.
5. Все числовые confidence/probability значения должны быть в диапазоне `0..1`, округляй до 4 знаков.
6. `sentiment.label` строго один из: `positive`, `negative`, `neutral`.
7. `emotions` использует только ключи: `anger`, `fear`, `joy`, `sadness`, `surprise`, `disgust`. Если эмоция не выражена, ставь `0.0`.
8. `aspects` максимум 3 элемента. Аспект - короткая предметная область, например `regulation`, `banking`, `markets`, `war`, `public_health`, `technology`, `company_results`.
9. `minimal_enrichment.topic` должен быть коротким, 2-6 слов, на русском или английском в зависимости от языка сообщения.
10. `minimal_enrichment.key_entities` максимум 6 объектов. Типы сущностей: `PERSON`, `ORG`, `GPE`, `LOC`, `PRODUCT`, `EVENT`.
11. Не добавляй полей вне схемы ниже.

## Выходная схема на каждую строку

```json
{
  "request_id": "string",
  "event_id": "string",
  "preprocessed_message_id": "uuid",
  "channel": "string",
  "message_id": 123,
  "sentiment": {
    "label": "positive|negative|neutral",
    "score": 0.0,
    "positive_prob": 0.0,
    "negative_prob": 0.0,
    "neutral_prob": 0.0
  },
  "emotions": {
    "anger": 0.0,
    "fear": 0.0,
    "joy": 0.0,
    "sadness": 0.0,
    "surprise": 0.0,
    "disgust": 0.0
  },
  "aspects": [
    {
      "aspect": "string",
      "sentiment": "positive|negative|neutral",
      "score": 0.0
    }
  ],
  "minimal_enrichment": {
    "topic": "string",
    "summary": "one short sentence",
    "event_type": "policy|markets|company|conflict|crime|technology|public_health|society|other",
    "geo_country": "string|null",
    "geo_place": "string|null",
    "key_entities": [
      {
        "text": "string",
        "type": "PERSON|ORG|GPE|LOC|PRODUCT|EVENT",
        "normalized": "string"
      }
    ]
  },
  "quality": {
    "usable": true,
    "reason": "ok"
  }
}
```

## SQL mapping after validation

Primary mapping to `sentiment_results`:

- `preprocessed_message_id` -> `sentiment_results.preprocessed_message_id`
- `channel` -> `sentiment_results.channel`
- `message_id` -> `sentiment_results.message_id`
- `event_id` -> `sentiment_results.event_id`
- `sentiment.label` -> `sentiment_label`
- `sentiment.score` -> `sentiment_score`
- `sentiment.positive_prob` -> `positive_prob`
- `sentiment.negative_prob` -> `negative_prob`
- `sentiment.neutral_prob` -> `neutral_prob`
- `emotions.*` -> `emotion_*`
- `aspects` -> `aspects`
- `model_name` should be `gpt-manual-minimal-analysis`
- `model_version` should be the GPT model/version used by the operator
- `model_framework` should be `openai`

Temporary workaround mapping for missing topic/enrichment UI:

- Store `minimal_enrichment` in a staging JSONL file first.
- If needed for quick demo, load a simplified copy into `exp_enriched` using `cleaned_text`, `topic`, `sentiment`, `key_people`, `geo_country`, `geo_place`.
- Do not overwrite NER tables from this output unless a human validates entity spans; GPT output does not include reliable character offsets.
