FROM python:3.11-slim

WORKDIR /app

COPY message_persister/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY message_persister /app/message_persister
COPY schemas /app/schemas

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/message_persister/main.py", "--config", "/app/message_persister/config.yaml"]
