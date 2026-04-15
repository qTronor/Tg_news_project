FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY topic_clusterer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY topic_clusterer /app/topic_clusterer
COPY schemas /app/schemas

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/topic_clusterer/main.py", "--config", "/app/topic_clusterer/config.yaml"]
