FROM python:3.11-slim

WORKDIR /app

COPY preprocessor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY preprocessor /app/preprocessor
COPY schemas /app/schemas

# Model cache lives on a named volume so the fastText lid.176.bin download
# (~125MB) survives container rebuilds. Lazy download is gated by the
# language_detection.auto_download config flag.
ENV PYTHONUNBUFFERED=1 \
    PREPROCESSOR_MODEL_DIR=/app/models

RUN mkdir -p /app/models

CMD ["python", "/app/preprocessor/main.py", "--config", "/app/preprocessor/config.yaml"]
