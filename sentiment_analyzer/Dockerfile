FROM python:3.11-slim

WORKDIR /app

COPY sentiment_analyzer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY sentiment_analyzer /app/sentiment_analyzer
COPY schemas /app/schemas
COPY models /app/models

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/sentiment_analyzer/main.py", "--config", "/app/sentiment_analyzer/config.yaml"]
