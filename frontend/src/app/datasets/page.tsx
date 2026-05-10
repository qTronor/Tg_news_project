"use client";

import Link from "next/link";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useDatasets } from "@/lib/use-data";
import { Database, ExternalLink, Loader2 } from "lucide-react";

export default function DatasetsPage() {
  const { data = [], isLoading } = useDatasets();

  return (
    <PageTransition>
      <Header title="Quality Lab datasets" />
      <main className="p-6 space-y-4">
        <p className="text-sm text-muted-foreground">
          Datasets are Quality Lab artifacts built from review and annotation decisions for benchmarks and candidate training.
        </p>
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading datasets
          </div>
        ) : data.length === 0 ? (
          <Card className="text-sm text-muted-foreground">Quality Lab datasets пока не найдены.</Card>
        ) : (
          <div className="grid gap-3">
            {data.map((dataset) => (
              <Link key={dataset.id} href={`/datasets/${dataset.id}`}>
                <Card hover className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Database className="h-4 w-4 text-primary" />
                      <h2 className="truncate text-sm font-semibold text-foreground">{dataset.name}</h2>
                      <Badge variant="outline">{dataset.status}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {dataset.total_items || dataset.annotation_progress ? dataset.total_items : 0} items ·{" "}
                      {Math.round(dataset.annotation_progress || 0)}% annotated
                    </p>
                  </div>
                  <ExternalLink className="h-4 w-4 shrink-0 text-muted-foreground" />
                </Card>
              </Link>
            ))}
          </div>
        )}
      </main>
    </PageTransition>
  );
}
