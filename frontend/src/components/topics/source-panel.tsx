"use client";

import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { SourceStatusBadge } from "@/components/topics/source-status-badge";
import type { FirstSourcePayload } from "@/types";
import { format, parseISO } from "date-fns";

function formatTs(value?: string | null) {
  if (!value) return "n/a";
  return format(parseISO(value), "dd MMM HH:mm");
}

export function SourcePanel({ source }: { source?: FirstSourcePayload | null }) {
  const status = source?.source_status || "unknown";
  const display = source?.display_source;
  const explanation =
    (display?.explanation?.summary as string | undefined) ||
    (source?.exact_source?.explanation?.summary as string | undefined) ||
    (source?.inferred_source?.explanation?.summary as string | undefined) ||
    "No upstream source evidence is available yet.";

  return (
    <Card className="rounded-none border-primary/20 bg-card lg:col-span-3">
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>Source resolution</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            First source evidence, confidence and compact propagation chain.
          </p>
        </div>
        <SourceStatusBadge status={status} />
      </CardHeader>

      <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="border border-border bg-muted/30 p-4">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                First source
              </div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {display?.source_channel || "Not detected"}
              </div>
            </div>
            <div className="border border-border bg-muted/30 p-4">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                First seen
              </div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {formatTs(display?.source_message_date)}
              </div>
            </div>
            <div className="border border-border bg-muted/30 p-4">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                Type
              </div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {display?.source_type || "unknown"}
              </div>
            </div>
            <div className="border border-border bg-muted/30 p-4">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                Confidence
              </div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {display ? `${Math.round(display.source_confidence * 100)}%` : "0%"}
              </div>
            </div>
          </div>

          <div className="border border-border p-4">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              Snippet
            </div>
            <p className="mt-2 text-sm leading-6 text-foreground">
              {display?.source_snippet || "No source snippet available."}
            </p>
          </div>

          <div className="border border-border p-4">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              Explanation
            </div>
            <p className="mt-2 text-sm leading-6 text-foreground">{explanation}</p>
          </div>
        </div>

        <div className="border border-border p-4">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">
            Propagation
          </div>
          <div className="mt-3 space-y-3">
            {(source?.propagation_chain || []).length > 0 ? (
              source!.propagation_chain.slice(0, 6).map((link) => (
                <div
                  key={`${link.parent_event_id}-${link.child_event_id}`}
                  className="border border-border bg-muted/20 p-3"
                >
                  <div className="text-xs font-medium text-foreground">
                    {link.parent_channel || "Unknown"} #{link.parent_message_id || "?"}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {link.link_type} · {Math.round(link.link_confidence * 100)}%
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    {link.child_channel} #{link.child_message_id}
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">
                No compact propagation chain is available for this topic.
              </p>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
