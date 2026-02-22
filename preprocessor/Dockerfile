FROM python:3.11-slim

WORKDIR /app

COPY preprocessor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY preprocessor /app/preprocessor
COPY schemas /app/schemas

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/preprocessor/main.py", "--config", "/app/preprocessor/config.yaml"]
