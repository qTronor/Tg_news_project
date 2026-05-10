# Model Training Contour

This project uses a two-consent MLOps flow for user-labelled datasets:

1. Dataset Builder creates `dataset_versions`, `dataset_items`, annotation tasks and labels.
2. Dataset validation checks labels, class balance, split quality, empty text and train/test leakage.
3. Training preview shows dataset size, label distribution, split, base model, config and metrics.
4. `consent_to_train=true` is required before `training_jobs` is created.
5. `training_orchestrator` processes queued jobs and uses mock/tiny training mode by default.
6. Evaluation metrics are stored in `model_evaluation_results`.
7. The trained model is registered in `model_versions` as `candidate`.
8. `consent_to_deploy=true` is required before a model can become `deployed`.
9. Deployment history stores the previous production model for rollback.

Training is never started automatically after annotation. Deployment is never automatic after training.

## Supported Tasks

- `topic_classification`: `text -> topic_label`; MVP requires at least 2 classes and 10 examples per class.
- `sentiment_classification`: `text -> positive|negative|neutral`; at least 2 classes are required.
- `embedding_finetuning`: similar/dissimilar pairs or confirmed cluster labels. The system fine-tunes an embedding model used by `topic_clusterer`; it does not fine-tune HDBSCAN or UMAP.
- `ner_finetuning`: span labels are supported in the validation/registry architecture; full trainer is future work.

## API Flow

```bash
POST /analytics/datasets/{dataset_id}/validate
POST /analytics/training/jobs/preview
POST /analytics/training/jobs
GET  /analytics/training/jobs/{job_id}
GET  /analytics/models/{model_id}
POST /analytics/models/{model_id}/accept
POST /analytics/models/{model_id}/deploy
```

`POST /analytics/training/jobs` must include:

```json
{
  "dataset_id": "...",
  "task_type": "topic_classification",
  "base_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "training_config": { "mode": "mock" },
  "consent_to_train": true
}
```

`POST /analytics/models/{id}/deploy` must include:

```json
{
  "consent_to_deploy": true,
  "actor_role": "admin"
}
```

If either consent flag is missing or false, the API returns `400` and does not create a job or deploy a model.

## Running the Worker

For API-only MVP, Analytics API starts a background task after job creation. For a service-style deployment:

```bash
python training_orchestrator/main.py --config training_orchestrator/config.yaml
```

Environment overrides use `TRAINING_ORCHESTRATOR__` and nested `__`, for example:

```bash
TRAINING_ORCHESTRATOR__POSTGRES__HOST=postgres
TRAINING_ORCHESTRATOR__SERVICE__POLL_INTERVAL_SECONDS=5
```

## Production Inference Integration

Inference services should read the current active model through:

```http
GET /analytics/models/current?model_type=sentiment_classifier
GET /analytics/models/current?model_type=topic_classifier
GET /analytics/models/current?model_type=embedding_model
```

For MVP, deployment updates the registry and history. A service reload mechanism can poll this endpoint periodically or reload on a future Kafka `model.deployment.completed` event.

## Rollback

Deployment writes `model_deployment_history.previous_model_version_id`. Rollback re-deploys that previous version through `POST /analytics/models/{id}/rollback`.

## Future Work

- Real transformer fine-tuning workers.
- Full NER trainer.
- Kafka producer/consumer implementation for training lifecycle topics.
- Artifact store integration with checksum and retention policy.
- Strict auth-service role propagation for ML Engineer.
