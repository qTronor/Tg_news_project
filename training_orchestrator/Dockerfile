FROM python:3.11-slim

WORKDIR /app
COPY training_orchestrator/requirements.txt /app/training_orchestrator/requirements.txt
RUN pip install --no-cache-dir -r /app/training_orchestrator/requirements.txt
COPY analytics_api /app/analytics_api
COPY training_orchestrator /app/training_orchestrator
CMD ["python", "training_orchestrator/main.py", "--config", "training_orchestrator/config.yaml"]
