FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY collector /app/collector
COPY main.py /app/main.py
COPY config.example.yaml /app/config.example.yaml

# Default command collects using config.yaml (mount it)
ENTRYPOINT ["python", "-m", "collector.cli"]
CMD ["collect", "--config", "config.yaml"]
