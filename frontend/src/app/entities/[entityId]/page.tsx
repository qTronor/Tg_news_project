"use client";

import { use } from "react";
import { format, parseISO } from "date-fns";
import Link from "next/link";
import { ArrowLeft, ExternalLink, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Badge } from "@/components/ui/badge";
import { VolumeLineChart } from "@/components/charts/volume-line";
import { EntityMergeDialog } from "@/components/EntityMergeDialog";
import { useEntity, useEntityAliases, useEntityMentionTimeline } from "@/lib/use-data";
import { useTranslation } from "@/lib/i18n";
import { entityTypeColor } from "@/lib/utils";

const SOURCE_LABEL: Record<string, string> = {
  rule: "rule",
  dictionary: "dict",
  fuzzy: "fuzzy",
  embedding: "embed",
  manual: "manual",
  model: "model",
};

export default function EntityDetailPage({ params }: { params: Promise<{ entityId: string }> }) {
  const { entityId } = use(params);
  const { t } = useTranslation();

  const { data: entity, isLoading: loadingEntity } = useEntity(entityId);
  const { data: aliases = [] } = useEntityAliases(entityId);
  const { data: timeline = [] } = useEntityMentionTimeline(entityId, "day");

  if (loadingEntity) {
    return (
      <>
        <Header title="..." />
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-6 h-6 text-primary animate-spin" />
        </div>
      </>
    );
  }

  if (!entity) {
    return (
      <>
        <Header title="Not found" />
        <div className="p-6">
          <p className="text-muted-foreground">Entity not found.</p>
          <Link href="/entities" className="mt-4 inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
            <ArrowLeft className="w-4 h-4" /> {t("entities.backToEntities")}
          </Link>
        </div>
      </>
    );
  }

  const displayName = entity.canonical_name || entity.text;
  const altName = entity.canonical_name && entity.canonical_name !== entity.text ? entity.text : null;
  const timelineData = timeline.map(p => ({ time: p.time, count: p.mention_count }));
  const isMerged = Boolean(entity.merged_into_id);

  return (
    <>
      <Header title={displayName} />
      <PageTransition>
        <div className="p-6 space-y-6 max-w-4xl">
          <Link
            href="/entities"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            {t("entities.backToEntities")}
          </Link>

          {isMerged && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-600 dark:text-amber-400">
              This entity has been merged into{" "}
              <Link href={`/entities/${entity.merged_into_id}`} className="underline font-medium">
                another entity
              </Link>.
            </div>
          )}

          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-card rounded-xl border border-border p-6 space-y-3"
          >
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <h1 className="text-2xl font-semibold text-foreground">{displayName}</h1>
                {altName && (
                  <p className="text-sm text-muted-foreground mt-0.5">{altName}</p>
                )}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="entity" color={entityTypeColor(entity.type)}>
                  {entity.type}
                </Badge>
                {!isMerged && (
                  <EntityMergeDialog entityId={entityId} entityName={displayName} />
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-2 border-t border-border">
              <Stat label={t("entities.mentions")} value={entity.mention_count ?? "—"} />
              <Stat label={t("entities.channels")} value={entity.channel_count ?? "—"} />
              <Stat label={t("entities.topics")} value={entity.topic_count ?? "—"} />
              {entity.wikidata_id ? (
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs text-muted-foreground uppercase tracking-wide">{t("entities.wikidataLink")}</span>
                  <a
                    href={`https://www.wikidata.org/wiki/${entity.wikidata_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-primary hover:underline inline-flex items-center gap-1"
                  >
                    {entity.wikidata_id}
                    <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              ) : (
                <Stat label={t("entities.wikidataLink")} value="—" />
              )}
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
              {entity.first_seen_at && (
                <MetaRow label={t("entities.firstSeen")} value={format(parseISO(entity.first_seen_at), "d MMM yyyy")} />
              )}
              {entity.last_seen_at && (
                <MetaRow label={t("entities.lastSeen")} value={format(parseISO(entity.last_seen_at), "d MMM yyyy")} />
              )}
              {entity.source_model && (
                <MetaRow label={t("entities.sourceModel")} value={entity.source_model} />
              )}
            </div>
          </motion.div>

          {timelineData.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.08 }}
              className="bg-card rounded-xl border border-border p-5"
            >
              <h2 className="text-sm font-semibold text-foreground mb-4">{t("entities.mentionTimeline")}</h2>
              <VolumeLineChart data={timelineData} />
            </motion.div>
          )}

          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.12 }}
            className="bg-card rounded-xl border border-border p-5"
          >
            <h2 className="text-sm font-semibold text-foreground mb-3">{t("entities.aliases")}</h2>
            {aliases.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("entities.noAliases")}</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {aliases.map((a, i) => (
                  <span
                    key={i}
                    title={`${t("entities.aliasSource")}: ${SOURCE_LABEL[a.source] ?? a.source}`}
                    className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border ${
                      a.is_primary
                        ? "bg-primary/10 text-primary border-primary/30"
                        : "bg-muted text-muted-foreground border-transparent"
                    }`}
                  >
                    {a.alias}
                    <span className="opacity-50">{SOURCE_LABEL[a.source] ?? a.source}</span>
                  </span>
                ))}
              </div>
            )}
          </motion.div>
        </div>
      </PageTransition>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground uppercase tracking-wide">{label}</span>
      <span className="text-lg font-semibold text-foreground">{value}</span>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground uppercase tracking-wide">{label}</span>
      <span className="text-sm text-foreground">{value}</span>
    </div>
  );
}