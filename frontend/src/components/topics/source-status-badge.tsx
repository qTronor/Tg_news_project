"use client";

import { Badge } from "@/components/ui/badge";
import type { SourceStatus } from "@/types";

const SOURCE_STATUS_STYLES: Record<SourceStatus, { label: string; color: string }> = {
  exact: { label: "Exact", color: "#15803d" },
  probable: { label: "Probable", color: "#d97706" },
  unknown: { label: "Unknown", color: "#64748b" },
};

export function SourceStatusBadge({
  status,
  className,
}: {
  status: SourceStatus;
  className?: string;
}) {
  const style = SOURCE_STATUS_STYLES[status];
  return (
    <Badge variant="entity" color={style.color} className={className}>
      {style.label}
    </Badge>
  );
}
