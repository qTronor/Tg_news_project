"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { useDataset } from "@/lib/use-data";
import type { TrainingTaskType } from "@/types";
import { AlertTriangle, CheckCircle2, Loader2, Play, RefreshCw, XCircle } from "lucide-react";
import { useState } from "react";

const TASKS: TrainingTaskType[] = [
  "topic_classification",
  "sentiment_classification",
  "embedding_finetuning",
  "ner_finetuning",
];

function StatusIcon({ status }: { status?: string }) {
  if (status === "valid") return <CheckCircle2 className="h-4 w-4 text-green-600" />;
  if (status === "warning") return <AlertTriangle className="h-4 w-4 text-amber-600" />;
  if (status === "invalid") return <XCircle className="h-4 w-4 text-red-600" />;
  return null;
}

export default function DatasetDetailPage() {
  const params = useParams<{ id: string }>();
  const [taskType, setTaskType] = useState<TrainingTaskType>("topic_classification");
  const queryClient = useQueryClient();
  const { data: dataset, isLoading } = useDataset(params.id, taskType);
  const validation = dataset?.validation;

  const validate = useMutation({
    mutationFn: () => api.validateDataset(params.id, taskType),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dataset", params.id, taskType] }),
  });

  return (
    <PageTransition>
      <Header title={dataset?.name ?? "Quality Lab dataset"} />
      <main className="p-6 space-y-4">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading dataset
          </div>
        ) : !dataset ? (
          <Card>Dataset not found</Card>
        ) : (
          <>
            <Card className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold">{dataset.name}</h2>
                  <p className="text-xs text-muted-foreground">
                    {dataset.total_items} items · {dataset.annotated_count} annotated · {dataset.status}
                  </p>
                </div>
                <select
                  value={taskType}
                  onChange={(event) => setTaskType(event.target.value as TrainingTaskType)}
                  className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
                >
                  {TASKS.map((task) => <option key={task} value={task}>{task}</option>)}
                </select>
              </div>
              <p className="text-sm text-muted-foreground">
                Этот датасет используется в Quality Lab для бенчмарков и controlled candidate-training. Обучение стартует только после вашего подтверждения, а новая модель не заменит текущую автоматически.
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => validate.mutate()}
                  disabled={validate.isPending}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
                >
                  {validate.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Проверить датасет
                </button>
                <Link
                  href={`/training/new?datasetId=${encodeURIComponent(dataset.id)}&taskType=${encodeURIComponent(taskType)}`}
                  className={validation?.status === "invalid" ? "pointer-events-none opacity-50" : ""}
                >
                  <button
                    disabled={validation?.status === "invalid"}
                    className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium disabled:opacity-50"
                  >
                  <Play className="h-4 w-4" /> Подготовить candidate training
                  </button>
                </Link>
              </div>
            </Card>

            <Card className="space-y-4">
              <div className="flex items-center gap-2">
                <StatusIcon status={validation?.status} />
                <h3 className="text-sm font-semibold">Quality validation report</h3>
                {validation?.status && <Badge variant="outline">{validation.status}</Badge>}
              </div>
              {!validation ? (
                <p className="text-sm text-muted-foreground">Запустите проверку датасета перед подготовкой обучения.</p>
              ) : (
                <>
                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="rounded-lg bg-muted/40 p-3 text-sm">Size: {validation.dataset_size}</div>
                    <div className="rounded-lg bg-muted/40 p-3 text-sm">Labeled: {validation.labeled_items}</div>
                    <div className="rounded-lg bg-muted/40 p-3 text-sm">Empty texts: {validation.empty_text_count}</div>
                  </div>
                  <div>
                    <h4 className="mb-2 text-xs font-semibold text-muted-foreground">Labels</h4>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(validation.label_distribution).map(([label, count]) => (
                        <Badge key={label} variant="topic">{label}: {count}</Badge>
                      ))}
                    </div>
                  </div>
                  {[...validation.errors, ...validation.warnings].map((message) => (
                    <p key={message} className="rounded-lg border border-border bg-muted/30 p-3 text-sm">{message}</p>
                  ))}
                </>
              )}
            </Card>
          </>
        )}
      </main>
    </PageTransition>
  );
}
