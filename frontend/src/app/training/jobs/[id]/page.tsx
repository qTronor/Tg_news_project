"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTrainingJob } from "@/lib/use-data";
import { api } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

export default function TrainingJobDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: job, isLoading } = useTrainingJob(params.id);
  const logs = useQuery({
    queryKey: ["trainingJobLogs", params.id],
    queryFn: () => api.getTrainingJobLogs(params.id),
    refetchInterval: 5_000,
  });
  return (
    <PageTransition>
      <Header title="Candidate training job" />
      <main className="p-6 space-y-4">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading job</div>
        ) : !job ? (
          <Card>Candidate training job not found</Card>
        ) : (
          <>
            <Card className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold">{job.dataset_name}</h2>
                <Badge variant="outline">{job.status}</Badge>
                <Badge variant="topic">{job.task_type}</Badge>
              </div>
              <p className="text-sm text-muted-foreground">{job.base_model}</p>
              <p className="text-sm">Модель обучается как candidate и не используется в рабочем pipeline без отдельного deploy consent.</p>
              {job.error_message && <p className="rounded-lg bg-red-500/10 p-3 text-sm text-red-600">{job.error_message}</p>}
              {job.candidate_model && (
                <Link href={`/models/${job.candidate_model.id}`}>
                  <button className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground">Open candidate model</button>
                </Link>
              )}
            </Card>
            <Card>
              <h3 className="mb-3 text-sm font-semibold">Metrics</h3>
              <pre className="overflow-auto rounded-lg bg-muted/40 p-3 text-xs">
                {JSON.stringify(job.candidate_model?.metrics ?? job.evaluations ?? {}, null, 2)}
              </pre>
            </Card>
            <Card>
              <h3 className="mb-3 text-sm font-semibold">Logs</h3>
              <div className="space-y-2">
                {(logs.data ?? []).map((entry) => (
                  <div key={entry.id} className="rounded-lg bg-muted/40 p-2 text-xs">
                    <span className="font-semibold">{entry.level}</span> · {entry.message}
                  </div>
                ))}
              </div>
            </Card>
          </>
        )}
      </main>
    </PageTransition>
  );
}
