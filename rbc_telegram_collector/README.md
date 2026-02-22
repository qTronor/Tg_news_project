# Telegram collector (RBC + any channels)

Сервис для выгрузки постов из публичных Telegram-каналов через MTProto (Telethon).
По умолчанию в примере — официальный канал РБК `@rbc_news`.

## 1) Быстрый старт (локально)

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
cp config.example.yaml config.yaml
```

### Telegram API доступ
Нужны `api_id` и `api_hash` (берутся на https://my.telegram.org).
Укажите их переменными окружения:

```bash
# Windows PowerShell:
$env:TG_API_ID="123456"
$env:TG_API_HASH="0123456789abcdef0123456789abcdef"
```

### Вариант A (проще): интерактивный логин (создаст файл сессии)
Первый запуск попросит телефон и код из Telegram, затем сохранит `.session` файл.

```bash
python -m collector.cli collect --config config.yaml
```

### Вариант B (идеально для микросервиса): StringSession (без интерактива)
Сгенерируйте строковую сессию локально:

```bash
python -m collector.cli make-session
```

Сохраните выведенную строку в переменную окружения `TG_STRING_SESSION`, а затем запускайте сбор уже без вопросов.

## 2) Выходные данные

По умолчанию пишет `data/<channel>.jsonl` (по строке JSON на пост).
При повторном запуске использует `state/state.json` и докачивает только новые посты.

## 3) Добавление других каналов

Откройте `config.yaml` и добавьте еще один объект в `channels`.

## 4) Запуск через Docker Compose

1. Создайте файл `.env` в корне проекта:
```bash
# .env
TG_API_ID=your_api_id_here
TG_API_HASH=your_api_hash_here
# Опционально:
# TG_STRING_SESSION=your_string_session_here
```

2. Убедитесь, что создан `config.yaml` (скопируйте из `config.example.yaml`)

3. Запустите:
```bash
docker-compose up
```

Docker Compose автоматически прочитает переменные из `.env` файла.

## 5) Запуск на сервере

См. подсказку в конце ответа ассистента (ssh/scp + venv + запуск).
