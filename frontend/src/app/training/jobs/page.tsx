"use client";

import Link from "next/link";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTrainingJobs } from "@/lib/use-data";
import { Loader2 } from "lucide-react";

export default function TrainingJobsPage() {
  const { data = [], isLoading } = useTrainingJobs();
  return (
    <PageTransition>
      <Header title="Candidate training jobs" />
      <main className="p-6 space-y-3">
        <p className="text-sm text-muted-foreground">
          Quality Lab training jobs create evaluated candidates only. They do not deploy models automatically.
        </p>
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading jobs</div>
        ) : data.length === 0 ? (
          <Card className="text-sm text-muted-foreground">Candidate training jobs пока не найдены.</Card>
        ) : data.map((job) => (
          <Link key={job.id} href={`/training/jobs/${job.id}`}>
            <Card hover className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="truncate text-sm font-semibold">{job.dataset_name}</h2>
                  <Badge variant="outline">{job.status}</Badge>
                  <Badge variant="topic">{job.task_type}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{job.base_model}</p>
              </div>
              {job.candidate_model && <Badge variant="new">candidate</Badge>}
            </Card>
          </Link>
        ))}
      </main>
    </PageTransition>
  );
}
