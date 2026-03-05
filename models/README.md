# Fine-tuned Models

This directory stores fine-tuned ML model artifacts exported from the Jupyter notebook
`telegram_pipeline_prototype (3).ipynb`.

## Expected structure

```
models/
├── sentiment_clf/        # Fine-tuned DeepPavlov/rubert-base-cased for sentiment
│   ├── config.json
│   ├── pytorch_model.bin (or model.safetensors)
│   ├── tokenizer.json
│   ├── tokenizer_config.json
│   ├── vocab.txt
│   ├── label2id.json
│   └── id2label.json
├── topic_clf/            # Fine-tuned DeepPavlov/rubert-base-cased for topic classification
│   ├── config.json
│   ├── pytorch_model.bin (or model.safetensors)
│   ├── tokenizer.json
│   ├── tokenizer_config.json
│   ├── vocab.txt
│   ├── label2id.json
│   └── id2label.json
└── README.md
```

## How to populate

Run the notebook with labeled data, then export artifacts:

```python
import shutil
shutil.make_archive("sentiment_clf", "zip", ART_DIR / "sentiment_clf")
shutil.make_archive("topic_clf", "zip", ART_DIR / "topic_clf")
```

Unzip into this directory.

## Fallback behavior

If a fine-tuned model is not present, services fall back to pretrained models:
- sentiment_analyzer → `blanchefort/rubert-base-cased-sentiment` (HuggingFace Hub)
- topic classification is not used by topic_clusterer (which only does embedding + clustering)
