FROM python:3.11-slim

WORKDIR /app

COPY ner_extractor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY ner_extractor /app/ner_extractor
COPY schemas /app/schemas

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/ner_extractor/main.py", "--config", "/app/ner_extractor/config.yaml"]
