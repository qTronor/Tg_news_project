FROM python:3.11-slim

WORKDIR /app

COPY analytics_duckdb/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY analytics_duckdb /app/analytics_duckdb

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/analytics_duckdb/main.py", "--config", "/app/analytics_duckdb/config.yaml"]
