"use client";

import Link from "next/link";
import { Loader2, Sparkles, TrendingUp } from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { useNovelTopics } from "@/lib/use-data";
import { entityTypeColor } from "@/lib/utils";

function score(value?: number | null) {
  return value == null ? "0.00" : value.toFixed(2);
}

export default function NovelTopicsPage() {
  const { data: topics = [], isLoading } = useNovelTopics(0.55);

  return (
    <>
      <Header title="Новые темы" />
      <PageTransition>
        <div className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-muted-foreground">
                Темы со статусом new и кандидаты с высоким novelty_score
              </p>
            </div>
            <div className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs text-muted-foreground">
              <Sparkles className="h-4 w-4 text-primary" />
              {topics.length} candidates
            </div>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : topics.length === 0 ? (
            <div className="rounded-lg border border-border bg-card p-8 text-sm text-muted-foreground">
              Новых тем и кандидатов по текущему порогу не найдено.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {topics.map((topic) => {
                const explanation = topic.novelty_explanation as
                  | { summary?: string; reasons?: string[]; new_entities?: string[] }
                  | null
                  | undefined;
                return (
                  <Link key={topic.cluster_id} href={`/topics/${topic.cluster_id}`}>
                    <Card hover className="h-full">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="truncate text-base font-semibold text-foreground">
                              {topic.label}
                            </h3>
                            <Badge variant={topic.novelty_status === "new" ? "new" : "default"}>
                              {topic.novelty_status === "new" ? "NEW" : "CANDIDATE"}
                            </Badge>
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {topic.message_count} сообщений · {topic.channel_count} каналов
                          </p>
                        </div>
                        <div className="shrink-0 text-right">
                          <div className="text-lg font-semibold text-foreground">
                            {score(topic.novelty_score)}
                          </div>
                          <div className="text-[11px] uppercase text-muted-foreground">
                            novelty
                          </div>
                        </div>
                      </div>

                      <div className="mt-4 grid grid-cols-[1fr_auto] items-center gap-3">
                        <Sparkline data={topic.sparkline} width={180} height={34} />
                        <div className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                          <TrendingUp className="h-3.5 w-3.5" />
                          рост
                        </div>
                      </div>

                      {explanation?.summary && (
                        <p className="mt-3 line-clamp-2 text-sm text-foreground">
                          {explanation.summary}
                        </p>
                      )}

                      <div className="mt-3 flex flex-wrap gap-1">
                        {topic.top_keywords.slice(0, 5).map((keyword) => (
                          <Badge key={keyword} className="text-[10px]">
                            {keyword}
                          </Badge>
                        ))}
                        {topic.top_entities.slice(0, 4).map((entity) => (
                          <Badge
                            key={entity.id}
                            variant="entity"
                            color={entityTypeColor(entity.type)}
                            className="text-[10px]"
                          >
                            {entity.text}
                          </Badge>
                        ))}
                      </div>

                      {explanation?.reasons?.[0] && (
                        <p className="mt-3 text-xs text-muted-foreground">
                          {explanation.reasons[0]}
                        </p>
                      )}
                    </Card>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </PageTransition>
    </>
  );
}
