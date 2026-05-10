"use client";

import { useParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { useModel } from "@/lib/use-data";
import { AlertTriangle, Loader2 } from "lucide-react";

export default function ModelDetailPage() {
  const params = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: model, isLoading } = useModel(params.id);
  const [deployOpen, setDeployOpen] = useState(false);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["model", params.id] });
  const accept = useMutation({ mutationFn: () => api.acceptModel(params.id), onSuccess: refresh });
  const reject = useMutation({ mutationFn: () => api.rejectModel(params.id), onSuccess: refresh });
  const deploy = useMutation({ mutationFn: () => api.deployModel(params.id), onSuccess: () => { setDeployOpen(false); refresh(); } });
  const rollback = useMutation({ mutationFn: () => api.rollbackModel(params.id), onSuccess: refresh });

  const comparison = model?.metrics?.comparison_to_baseline as Record<string, unknown> | undefined;
  const blocked = model?.metrics?.deployment_blocked === true;

  return (
    <PageTransition>
      <Header title={model?.model_name ?? "Model card"} />
      <main className="p-6 space-y-4">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading model</div>
        ) : !model ? (
          <Card>Model not found</Card>
        ) : (
          <>
            <Card className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold">{model.model_name}</h2>
                <Badge variant="outline">{model.status}</Badge>
                <Badge variant="topic">{model.model_type}</Badge>
              </div>
              <p className="text-sm text-muted-foreground">{model.base_model}</p>
              <p className="text-sm">Модель обучена как candidate. Она не используется в рабочем pipeline, пока вы явно не подтвердите deploy.</p>
              <p className="rounded-lg bg-muted/40 p-3 text-xs">{model.artifact_path}</p>
              {comparison && (
                <div className="rounded-lg border border-border p-3 text-sm">
                  Baseline comparison: {String(comparison.metric_name)} · baseline {String(comparison.baseline_value ?? "n/a")} · candidate {String(comparison.candidate_value ?? "n/a")} · delta {String(comparison.delta ?? "n/a")}
                </div>
              )}
              {blocked && (
                <p className="flex items-center gap-2 rounded-lg bg-red-500/10 p-3 text-sm text-red-600">
                  <AlertTriangle className="h-4 w-4" /> Candidate is worse than baseline on primary metric. Deployment is blocked.
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <button onClick={() => accept.mutate()} disabled={!["candidate", "accepted"].includes(model.status)} className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">Принять модель</button>
                <button onClick={() => reject.mutate()} disabled={!["candidate", "accepted"].includes(model.status)} className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">Отклонить модель</button>
                <button onClick={() => setDeployOpen(true)} disabled={blocked || !["candidate", "accepted", "deployed"].includes(model.status)} className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">Explicit deploy</button>
                <button onClick={() => rollback.mutate()} disabled={model.status !== "deployed"} className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">Rollback</button>
              </div>
            </Card>
            <Card>
              <h3 className="mb-3 text-sm font-semibold">Metrics</h3>
              <pre className="overflow-auto rounded-lg bg-muted/40 p-3 text-xs">{JSON.stringify(model.metrics, null, 2)}</pre>
            </Card>
            <Card>
              <h3 className="mb-3 text-sm font-semibold">Evaluations</h3>
              <pre className="overflow-auto rounded-lg bg-muted/40 p-3 text-xs">{JSON.stringify(model.evaluations ?? [], null, 2)}</pre>
            </Card>
          </>
        )}

        {deployOpen && model && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-lg rounded-xl border border-border bg-card p-5 shadow-xl">
              <h3 className="text-base font-semibold">Confirm explicit deploy</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Вы уверены, что хотите внедрить эту candidate-модель в рабочий pipeline? Текущая явно deployed-модель будет заменена, но rollback останется доступен.
              </p>
              <p className="mt-3 text-sm">После внедрения эта модель станет активной для выбранного типа анализа. Предыдущая версия будет сохранена для rollback.</p>
              <div className="mt-5 flex justify-end gap-2">
                <button onClick={() => setDeployOpen(false)} className="rounded-lg border border-border px-3 py-2 text-sm">Cancel</button>
                <button onClick={() => deploy.mutate()} disabled={deploy.isPending} className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
                  {deploy.isPending ? "Deploying..." : "Explicit deploy"}
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </PageTransition>
  );
}
