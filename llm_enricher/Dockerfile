FROM python:3.11-slim

WORKDIR /app

COPY llm_enricher/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY llm_enricher /app/llm_enricher

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/llm_enricher/main.py", "--config", "/app/llm_enricher/config.yaml"]
