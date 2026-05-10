"use client";

import Link from "next/link";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useModels } from "@/lib/use-data";
import { Box, Loader2 } from "lucide-react";

export default function ModelsPage() {
  const { data = [], isLoading } = useModels();
  const deployed = data.filter((model) => model.status === "deployed");
  const candidates = data.filter((model) => model.status !== "deployed");

  return (
    <PageTransition>
      <Header title="Quality Lab model registry" />
      <main className="p-6 space-y-5">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading models</div>
        ) : (
          <>
            <section className="space-y-3">
              <h2 className="text-sm font-semibold">Explicitly deployed models</h2>
              {deployed.length === 0 ? <Card className="text-sm text-muted-foreground">No explicitly deployed models yet.</Card> : deployed.map((model) => (
                <ModelRow key={model.id} model={model} />
              ))}
            </section>
            <section className="space-y-3">
              <h2 className="text-sm font-semibold">Candidates and history</h2>
              {candidates.length === 0 ? <Card className="text-sm text-muted-foreground">No candidate models yet.</Card> : candidates.map((model) => (
                <ModelRow key={model.id} model={model} />
              ))}
            </section>
          </>
        )}
      </main>
    </PageTransition>
  );
}

function ModelRow({ model }: { model: { id: string; model_name: string; model_type: string; version: string; status: string; artifact_path: string } }) {
  return (
    <Link href={`/models/${model.id}`}>
      <Card hover className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Box className="h-4 w-4 text-primary" />
            <h3 className="truncate text-sm font-semibold">{model.model_name}</h3>
            <Badge variant="outline">{model.status}</Badge>
            <Badge variant="topic">{model.model_type}</Badge>
          </div>
          <p className="mt-1 truncate text-xs text-muted-foreground">{model.version} · {model.artifact_path}</p>
        </div>
      </Card>
    </Link>
  );
}
