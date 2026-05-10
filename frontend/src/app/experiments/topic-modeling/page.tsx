"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Loader2, Play, RefreshCw } from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { useGlobalTimeRange } from "@/components/providers";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useDatasets, useTopicExperimentMetrics, useTopicExperiments } from "@/lib/use-data";

const MODEL_OPTIONS = [
  { key: "sbert_umap_hdbscan", label: "SBERT + UMAP + HDBSCAN" },
  { key: "bertopic_like", label: "BERTopic-like" },
  { key: "lda", label: "LDA" },
  { key: "nmf", label: "NMF" },
];

const METRIC_LABELS: Record<string, string> = {
  topic_coherence: "Coherence",
  topic_diversity: "Diversity",
  silhouette: "Silhouette",
  davies_bouldin: "Davies-Bouldin",
  outlier_ratio: "Outliers",
  cluster_count: "Topics",
  stability_ari_vs_previous: "Stability ARI",
  stability_nmi_vs_previous: "Stability NMI",
};

export default function TopicModelingExperimentsPage() {
  const queryClient = useQueryClient();
  const { range } = useGlobalTimeRange();
  const { data: experiments, isLoading } = useTopicExperiments();
  const { data: datasets = [] } = useDatasets();
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | null>(null);
  const [models, setModels] = useState(["sbert_umap_hdbscan", "lda", "nmf"]);
  const [channels, setChannels] = useState("");
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [maxMessages, setMaxMessages] = useState(1500);
  const [runnerCommand, setRunnerCommand] = useState<string | null>(null);

  const selectedId = selectedExperimentId || experiments?.[0]?.id || null;
  const { data: metrics } = useTopicExperimentMetrics(selectedId);
  const readyDatasets = useMemo(
    () => datasets.filter((dataset) => dataset.status === "ready"),
    [datasets]
  );
  const selectedDataset = readyDatasets.find((dataset) => dataset.id === datasetVersionId) || null;

  const mutation = useMutation({
    mutationFn: () =>
      api.runTopicExperiment({
        name: `topic-benchmark-${new Date().toISOString().slice(0, 10)}`,
        from: range.from,
        to: range.to,
        dataset_version_id: datasetVersionId || undefined,
        channels: channels
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        models,
        max_messages: maxMessages,
        seed: 42,
        n_topics: 12,
      }),
    onSuccess: (payload) => {
      setRunnerCommand(payload.runner_command);
      setSelectedExperimentId(payload.experiment_id);
      queryClient.invalidateQueries({ queryKey: ["topicExperiments"] });
      queryClient.invalidateQueries({ queryKey: ["topicExperimentMetrics"] });
    },
  });

  const baseline = metrics?.runs.find((run) => run.is_baseline);
  const metricNames = useMemo(() => {
    const names = new Set<string>();
    metrics?.runs.forEach((run) => Object.keys(run.metrics).forEach((name) => names.add(name)));
    return Array.from(names).sort((a, b) => (METRIC_LABELS[a] || a).localeCompare(METRIC_LABELS[b] || b));
  }, [metrics]);

  const canSubmit = models.length >= 3 && maxMessages >= 100;

  return (
    <>
      <Header title="Topic modeling benchmark" />
      <PageTransition>
        <div className="space-y-5 p-6">
          <Card>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <BarChart3 className="h-5 w-5 text-primary" />
                  <h2 className="text-lg font-semibold">Запуск эксперимента</h2>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Можно запускать benchmark либо по глобальному окну времени, либо по готовому dataset.
                  Для ноутбука держите выборку в диапазоне 1000-2500 сообщений.
                </p>
              </div>
              <button
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending || !canSubmit}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-60"
              >
                {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Создать benchmark
              </button>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-[1.2fr_1fr_1fr_180px]">
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground">Модели</label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {MODEL_OPTIONS.map((option) => (
                    <button
                      key={option.key}
                      onClick={() =>
                        setModels((current) =>
                          current.includes(option.key)
                            ? current.filter((item) => item !== option.key)
                            : [...current, option.key]
                        )
                      }
                      className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
                        models.includes(option.key)
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border text-muted-foreground"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Для сравнения держите минимум 3 модели в одном experiment.
                </p>
              </div>

              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground">Dataset</label>
                <select
                  value={datasetVersionId}
                  onChange={(event) => setDatasetVersionId(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                >
                  <option value="">Использовать окно времени</option>
                  {readyDatasets.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name} ({dataset.total_items})
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-muted-foreground">
                  {selectedDataset
                    ? `Dataset override: ${selectedDataset.window_start.slice(0, 10)} - ${selectedDataset.window_end.slice(0, 10)}`
                    : "Если dataset выбран, его окно и каналы автоматически подставляются в benchmark."}
                </p>
              </div>

              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground">Каналы</label>
                <input
                  value={channels}
                  onChange={(event) => setChannels(event.target.value)}
                  disabled={Boolean(selectedDataset)}
                  placeholder={selectedDataset ? "Берутся из dataset" : "rbc_news, banksta"}
                  className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary disabled:opacity-60"
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  {selectedDataset
                    ? `Channels: ${selectedDataset.channels.join(", ") || "all"}`
                    : "Оставьте пустым, чтобы брать все каналы из текущего окна."}
                </p>
              </div>

              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground">Max messages</label>
                <input
                  type="number"
                  min={100}
                  max={5000}
                  value={maxMessages}
                  onChange={(event) => setMaxMessages(Number(event.target.value))}
                  className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                />
              </div>
            </div>

            {runnerCommand && (
              <div className="mt-4 rounded-lg border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                Worker mode включен. Новый experiment должен стартовать автоматически после создания.
                <div className="mt-2 text-[11px]">
                  Fallback command нужен только если worker-контейнер остановлен:
                  <div className="mt-1">
                    <code className="text-foreground">{runnerCommand}</code>
                  </div>
                </div>
              </div>
            )}

            {mutation.error && (
              <div className="mt-4 rounded-lg border border-amber-400/40 bg-amber-400/10 p-3 text-sm text-amber-200">
                {mutation.error instanceof Error ? mutation.error.message : "Failed to create benchmark"}
              </div>
            )}
          </Card>

          <div className="grid gap-5 xl:grid-cols-[360px_1fr]">
            <Card>
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold">Эксперименты</h2>
                <RefreshCw className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="mt-3 space-y-2">
                {isLoading && <p className="text-sm text-muted-foreground">Загрузка...</p>}
                {(experiments || []).map((experiment) => (
                  <button
                    key={experiment.id}
                    onClick={() => setSelectedExperimentId(experiment.id)}
                    className={`w-full rounded-lg border p-3 text-left transition-colors ${
                      selectedId === experiment.id ? "border-primary bg-primary/5" : "border-border hover:bg-accent"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold">{experiment.name}</span>
                      <Badge>{experiment.status}</Badge>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      dataset: {experiment.dataset_version}
                      {experiment.dataset_version_id ? " · linked" : " · ad-hoc"}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {experiment.completed_run_count}/{experiment.run_count} runs · seed {experiment.seed}
                    </p>
                  </button>
                ))}
                {!isLoading && (experiments || []).length === 0 && (
                  <p className="text-sm text-muted-foreground">Экспериментов пока нет.</p>
                )}
              </div>
            </Card>

            <Card>
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-base font-semibold">Сравнение метрик</h2>
                  <p className="text-xs text-muted-foreground">
                    {baseline?.status === "completed"
                      ? `Baseline: ${baseline.model_name}`
                      : baseline?.status === "failed"
                        ? "Baseline failed, остальные модели могли завершиться успешно."
                        : "Метрики появятся после запуска worker."}
                  </p>
                </div>
              </div>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[760px] text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase text-muted-foreground">
                      <th className="py-2 pr-3">Model</th>
                      {metricNames.map((name) => (
                        <th key={name} className="px-3 py-2">
                          {METRIC_LABELS[name] || name}
                        </th>
                      ))}
                      <th className="px-3 py-2">Clusters</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(metrics?.runs || []).map((run) => (
                      <tr key={run.run_id} className="border-b border-border/60">
                        <td className="py-3 pr-3">
                          <div className="font-medium">{run.model_name}</div>
                          <div className="text-xs text-muted-foreground">{run.status}</div>
                          {run.error_message && (
                            <div className="mt-1 text-[11px] text-amber-300">{run.error_message}</div>
                          )}
                        </td>
                        {metricNames.map((name) => (
                          <td key={name} className="px-3 py-3">
                            {formatMetric(run.metrics[name])}
                          </td>
                        ))}
                        <td className="px-3 py-3">
                          {run.cluster_run_id ? (
                            <Link className="text-primary underline-offset-4 hover:underline" href="/topics">
                              open
                            </Link>
                          ) : (
                            <span className="text-muted-foreground">pending</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {(metrics?.runs || []).length === 0 && (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    Метрики появятся после того, как worker обработает experiment.
                  </p>
                )}
              </div>
            </Card>
          </div>
        </div>
      </PageTransition>
    </>
  );
}

function formatMetric(value: unknown) {
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  return "json";
}
