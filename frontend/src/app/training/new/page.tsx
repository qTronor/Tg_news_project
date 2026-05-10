"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { TrainingPlan, TrainingTaskType } from "@/types";
import { AlertTriangle, Loader2, Play } from "lucide-react";

const BASE_MODELS: Record<TrainingTaskType, string[]> = {
  topic_classification: [
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "DeepPavlov/rubert-base-cased",
  ],
  sentiment_classification: [
    "cointegrated/rubert-tiny-sentiment-balanced",
    "cardiffnlp/twitter-xlm-roberta-base-sentiment",
  ],
  embedding_finetuning: [
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "intfloat/multilingual-e5-small",
  ],
  ner_finetuning: ["dslim/bert-base-NER"],
};

export default function NewTrainingPage() {
  const search = useSearchParams();
  const router = useRouter();
  const datasetId = search.get("datasetId") ?? "";
  const initialTask = (search.get("taskType") as TrainingTaskType) || "topic_classification";
  const [taskType, setTaskType] = useState<TrainingTaskType>(initialTask);
  const [baseModel, setBaseModel] = useState(BASE_MODELS[initialTask][0]);
  const [plan, setPlan] = useState<TrainingPlan | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const config = useMemo(() => ({ mode: "mock", epochs: 3, batch_size: 16 }), []);

  const preview = useMutation({
    mutationFn: () => api.previewTraining({ dataset_id: datasetId, task_type: taskType, base_model: baseModel, training_config: config }),
    onSuccess: setPlan,
  });
  const createJob = useMutation({
    mutationFn: () => api.createTrainingJob({
      dataset_id: datasetId,
      task_type: taskType,
      base_model: baseModel,
      training_config: config,
      consent_to_train: true,
    }),
    onSuccess: (job) => router.push(`/training/jobs/${job.id}`),
  });

  const invalid = plan?.validation_status === "invalid";
  const warning = plan?.validation_status === "warning";

  return (
    <PageTransition>
      <Header title="Prepare candidate training" />
      <main className="p-6 space-y-4">
        <Card className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <label className="space-y-1 text-sm">
              <span className="text-xs text-muted-foreground">Dataset ID</span>
              <input value={datasetId} readOnly className="w-full rounded-lg border border-border bg-muted/30 px-3 py-2" />
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-xs text-muted-foreground">Task type</span>
              <select
                value={taskType}
                onChange={(event) => {
                  const next = event.target.value as TrainingTaskType;
                  setTaskType(next);
                  setBaseModel(BASE_MODELS[next][0]);
                  setPlan(null);
                }}
                className="w-full rounded-lg border border-border bg-background px-3 py-2"
              >
                {Object.keys(BASE_MODELS).map((task) => <option key={task} value={task}>{task}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-xs text-muted-foreground">Base model</span>
              <select value={baseModel} onChange={(event) => setBaseModel(event.target.value)} className="w-full rounded-lg border border-border bg-background px-3 py-2">
                {BASE_MODELS[taskType].map((model) => <option key={model} value={model}>{model}</option>)}
              </select>
            </label>
          </div>
          <button
            onClick={() => preview.mutate()}
            disabled={!datasetId || preview.isPending}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {preview.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Preview candidate plan
          </button>
        </Card>

        {plan && (
          <Card className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold">{plan.dataset_name}</h2>
              <Badge variant="outline">{plan.validation_status}</Badge>
              <Badge variant="topic">{plan.task_type}</Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              Candidate training будет запущен только после вашего подтверждения. Новая модель не заменит текущую автоматически.
            </p>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-lg bg-muted/40 p-3 text-sm">Size: {plan.dataset_size}</div>
              <div className="rounded-lg bg-muted/40 p-3 text-sm">Base: {plan.base_model}</div>
              <div className="rounded-lg bg-muted/40 p-3 text-sm">Auto deploy: {String(plan.will_auto_deploy)}</div>
            </div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(plan.label_distribution).map(([label, count]) => <Badge key={label}>{label}: {count}</Badge>)}
            </div>
            {plan.warnings.map((message) => (
              <p key={message} className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
                <AlertTriangle className="h-4 w-4" /> {message}
              </p>
            ))}
            <button
              onClick={() => setModalOpen(true)}
              disabled={invalid}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              Start candidate training
            </button>
            {invalid && <p className="text-sm text-red-600">Invalid dataset: training disabled.</p>}
          </Card>
        )}

        {modalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-lg rounded-xl border border-border bg-card p-5 shadow-xl">
              <h3 className="text-base font-semibold">Confirm candidate training</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Вы уверены, что хотите запустить controlled candidate-training на этом датасете? Это создаст новую candidate-версию модели. Она не будет использоваться в рабочем pipeline до отдельного deploy-подтверждения.
              </p>
              {warning && <p className="mt-3 rounded-lg bg-amber-500/10 p-3 text-sm">Dataset has warnings. Confirm explicitly to continue.</p>}
              <div className="mt-5 flex justify-end gap-2">
                <button onClick={() => setModalOpen(false)} className="rounded-lg border border-border px-3 py-2 text-sm">Cancel</button>
                <button
                  onClick={() => createJob.mutate()}
                  disabled={createJob.isPending}
                  className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
                >
                  {createJob.isPending ? "Starting..." : "Confirm candidate training"}
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </PageTransition>
  );
}
