"use client";

import { useState } from "react";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";
import { useEntities } from "@/lib/use-data";
import { useQueryClient } from "@tanstack/react-query";

interface Props {
  entityId: string;
  entityName: string;
}

export function EntityMergeDialog({ entityId, entityName }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [targetId, setTargetId] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const { data: allEntities = [] } = useEntities();
  const suggestions = allEntities.filter(
    e => e.id !== entityId &&
      (search.length === 0 || (e.canonical_name || e.text).toLowerCase().includes(search.toLowerCase()))
  ).slice(0, 10);

  async function handleMerge() {
    if (!targetId) return;
    setLoading(true);
    setError(null);
    try {
      await api.mergeEntities(entityId, targetId, reason);
      setSuccess(true);
      queryClient.invalidateQueries({ queryKey: ["entity"] });
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      setTimeout(() => { setOpen(false); setSuccess(false); }, 1500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 px-3 py-2 bg-muted rounded-lg text-sm text-foreground hover:bg-accent transition-colors"
      >
        {t("entities.mergeButton")}
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-card rounded-xl border border-border p-6 w-full max-w-md mx-4 shadow-xl space-y-4">
        <h2 className="text-lg font-semibold text-foreground">{t("entities.mergeDialogTitle")}</h2>
        <p className="text-sm text-muted-foreground">
          Merging <span className="font-medium text-foreground">{entityName}</span> into another entity.
          {" "}{t("entities.confirmMerge")}
        </p>

        {success ? (
          <p className="text-sm text-positive font-medium">{t("entities.mergeSuccess")}</p>
        ) : (
          <>
            <div className="space-y-2">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Search target entity
              </label>
              <input
                type="text"
                value={search}
                onChange={e => { setSearch(e.target.value); setTargetId(""); }}
                placeholder="Entity name..."
                className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-primary/30"
              />
              {suggestions.length > 0 && !targetId && (
                <div className="border border-border rounded-lg overflow-hidden">
                  {suggestions.map(e => (
                    <button
                      key={e.id}
                      onClick={() => { setTargetId(e.id); setSearch(e.canonical_name || e.text); }}
                      className="w-full px-3 py-2 text-left text-sm hover:bg-accent transition-colors border-b border-border last:border-0"
                    >
                      <span className="font-medium">{e.canonical_name || e.text}</span>
                      <span className="ml-2 text-xs text-muted-foreground">{e.type}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="space-y-2">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                {t("entities.mergeReason")}
              </label>
              <input
                type="text"
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder="Optional reason..."
                className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>

            {error && (
              <p className="text-sm text-negative">{error}</p>
            )}

            <div className="flex items-center gap-3 justify-end pt-2">
              <button
                onClick={() => { setOpen(false); setError(null); }}
                disabled={loading}
                className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleMerge}
                disabled={loading || !targetId}
                className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium disabled:opacity-50 hover:bg-primary/90 transition-colors"
              >
                {loading ? "Merging..." : t("entities.mergeConfirm")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
