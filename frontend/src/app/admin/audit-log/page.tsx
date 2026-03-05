"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "@/lib/i18n";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/components/auth/auth-provider";
import { authApi } from "@/lib/auth";
import { ScrollText, Loader2, ChevronDown } from "lucide-react";
import { format, parseISO } from "date-fns";

interface AuditEntry {
  id: string;
  admin_id: string | null;
  admin_username: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

export default function AuditLogPage() {
  const { t } = useTranslation();
  const { isAdmin } = useAuth();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const LIMIT = 50;

  const fetchEntries = useCallback(
    async (off: number) => {
      try {
        const data = (await authApi.getAuditLog(LIMIT, off)) as AuditEntry[];
        if (off === 0) {
          setEntries(data);
        } else {
          setEntries((prev) => [...prev, ...data]);
        }
        setHasMore(data.length === LIMIT);
      } catch {
        /* handle */
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (isAdmin) fetchEntries(0);
  }, [isAdmin, fetchEntries]);

  const loadMore = () => {
    const next = offset + LIMIT;
    setOffset(next);
    fetchEntries(next);
  };

  if (!isAdmin) {
    return (
      <>
        <Header title={t("common.accessDenied")} />
        <PageTransition>
          <div className="flex items-center justify-center min-h-[60vh] text-muted-foreground">
            {t("admin.audit.forbidden")}
          </div>
        </PageTransition>
      </>
    );
  }

  const actionColor = (action: string) => {
    if (action.includes("edit")) return "var(--entity-org)";
    if (action.includes("toggle")) return "var(--entity-loc)";
    return "var(--entity-misc)";
  };

  return (
    <>
      <Header title={t("admin.audit.title")} />
      <PageTransition>
        <div className="p-6 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ScrollText className="w-5 h-5" />
                {t("admin.audit.subtitle")}
              </CardTitle>
            </CardHeader>
            <div className="p-5">
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-6 h-6 text-primary animate-spin" />
                </div>
              ) : entries.length === 0 ? (
                <p className="text-center py-8 text-sm text-muted-foreground">
                  {t("admin.audit.empty")}
                </p>
              ) : (
                <div className="space-y-2">
                  {entries.map((entry, i) => (
                    <motion.div
                      key={entry.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.01 }}
                      className="flex items-start gap-4 p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                    >
                      <div className="flex-1 min-w-0 space-y-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge
                            variant="entity"
                            color={actionColor(entry.action)}
                          >
                            {entry.action}
                          </Badge>
                          {entry.admin_username && (
                            <span className="text-xs text-muted-foreground">
                              {t("admin.audit.from")}{" "}
                              <span className="font-medium text-foreground">
                                {entry.admin_username}
                              </span>
                            </span>
                          )}
                        </div>
                        {entry.target_type && (
                          <p className="text-xs text-muted-foreground">
                            {entry.target_type}: {entry.target_id}
                          </p>
                        )}
                        {entry.new_value && (
                          <p className="text-xs text-muted-foreground font-mono break-all">
                            {JSON.stringify(entry.new_value)}
                          </p>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground whitespace-nowrap">
                        {format(parseISO(entry.created_at), "dd.MM.yy HH:mm")}
                        {entry.ip_address && (
                          <div className="text-[10px] opacity-60">
                            {entry.ip_address}
                          </div>
                        )}
                      </div>
                    </motion.div>
                  ))}

                  {hasMore && (
                    <button
                      onClick={loadMore}
                      className="w-full flex items-center justify-center gap-2 py-3 text-sm text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <ChevronDown className="w-4 h-4" />
                      {t("admin.audit.loadMore")}
                    </button>
                  )}
                </div>
              )}
            </div>
          </Card>
        </div>
      </PageTransition>
    </>
  );
}
