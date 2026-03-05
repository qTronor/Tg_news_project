"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Save, Loader2 } from "lucide-react";
import { useTranslation } from "@/lib/i18n";
import { authApi } from "@/lib/auth";
import type { Message } from "@/types";

interface Props {
  message: Message;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function MessageEditModal({ message, open, onClose, onSaved }: Props) {
  const { t } = useTranslation();
  const [sentimentScore, setSentimentScore] = useState(
    message.sentiment_score?.toString() ?? "0",
  );
  const [sentimentLabel, setSentimentLabel] = useState(
    message.sentiment_label ?? "",
  );
  const [topicLabel, setTopicLabel] = useState(message.topic_label ?? "");
  const [entities, setEntities] = useState(
    message.entities?.map((e) => e.text).join(", ") ?? "",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const changes: Record<string, unknown> = {};
      const scoreNum = parseFloat(sentimentScore);
      if (!isNaN(scoreNum) && scoreNum !== message.sentiment_score) {
        changes.sentiment_score = scoreNum;
      }
      if (sentimentLabel && sentimentLabel !== message.sentiment_label) {
        changes.sentiment_label = sentimentLabel;
      }
      if (topicLabel && topicLabel !== message.topic_label) {
        changes.topic_label = topicLabel;
      }
      if (entities) {
        const parsed = entities
          .split(",")
          .map((e) => e.trim())
          .filter(Boolean)
          .map((text) => ({ text, type: "MISC" }));
        changes.entities = parsed;
      }

      if (Object.keys(changes).length === 0) {
        onClose();
        return;
      }

      await authApi.editMessage(message.event_id, changes);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("edit.saveError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            onClick={(e) => e.stopPropagation()}
            className="bg-card rounded-2xl border border-border p-6 w-full max-w-lg shadow-2xl"
          >
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-foreground">
                {t("edit.title")}
              </h2>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-muted-foreground mb-4 line-clamp-2">
              {message.text}
            </p>

            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-foreground">
                    {t("edit.sentimentScore")}
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="-1"
                    max="1"
                    value={sentimentScore}
                    onChange={(e) => setSentimentScore(e.target.value)}
                    className="w-full px-3 py-2 bg-muted rounded-lg border border-border text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-foreground">
                    {t("edit.sentimentLabel")}
                  </label>
                  <select
                    value={sentimentLabel}
                    onChange={(e) => setSentimentLabel(e.target.value)}
                    className="w-full px-3 py-2 bg-muted rounded-lg border border-border text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                  >
                    <option value="">—</option>
                    <option value="Positive">Positive</option>
                    <option value="Neutral">Neutral</option>
                    <option value="Negative">Negative</option>
                  </select>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">
                  {t("edit.topic")}
                </label>
                <input
                  type="text"
                  value={topicLabel}
                  onChange={(e) => setTopicLabel(e.target.value)}
                  placeholder={t("edit.topicPlaceholder")}
                  className="w-full px-3 py-2 bg-muted rounded-lg border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">
                  {t("edit.entities")}
                </label>
                <input
                  type="text"
                  value={entities}
                  onChange={(e) => setEntities(e.target.value)}
                  placeholder={t("edit.entitiesPlaceholder")}
                  className="w-full px-3 py-2 bg-muted rounded-lg border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>

              {error && (
                <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive">
                  {error}
                </div>
              )}

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground rounded-lg hover:bg-accent transition-colors"
                >
                  {t("edit.cancel")}
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-all"
                >
                  {saving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Save className="w-4 h-4" />
                  )}
                  {t("edit.save")}
                </button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
