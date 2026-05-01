FROM python:3.11-slim

WORKDIR /app

# Install only requirements (with CPU-only torch to save space)
COPY sentiment_analyzer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r /app/requirements.txt

# Copy application code
COPY sentiment_analyzer /app/sentiment_analyzer
COPY schemas /app/schemas
COPY models /app/models

ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/sentiment_analyzer/main.py", "--config", "/app/sentiment_analyzer/config.yaml"]
