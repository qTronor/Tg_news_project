#!/bin/bash
docker exec telegram-news-postgres psql -U postgres -d telegram_news -c "SELECT version, description FROM schema_migrations ORDER BY version DESC LIMIT 5;"
docker exec telegram-news-postgres psql -U postgres -d telegram_news -c "\d sentiment_results" 2>/dev/null | grep -E "model_language|emotion_model|aspects_status" || echo "Checking NER..."
docker exec telegram-news-postgres psql -U postgres -d telegram_news -c "\d ner_results" 2>/dev/null | grep -E "model_backend|model_language" || echo "DB schema check complete"
