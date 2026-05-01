FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY topic_scorer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY topic_scorer /app/topic_scorer

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "/app/topic_scorer/main.py"]
CMD ["scheduled"]
