"use client";

import { useState, useCallback, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "@/lib/i18n";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  useAnnotationTasks, useAnnotationStats, useDatasets,
  useChannels, useAnnotationTopics,
} from "@/lib/use-data";
import { useAuth } from "@/components/auth/auth-provider";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle2, SkipForward, Tag, AlertCircle, Copy,
  ChevronRight, Loader2, BarChart2, Download, RefreshCw, BookOpen, Plus, X,
  ThumbsUp, ThumbsDown, Minus,
} from "lucide-react";
import type { AnnotationQuality, AnnotationTask, DatasetVersion } from "@/types";
import { format } from "date-fns";
import { ru } from "date-fns/locale";

// ─── Constants ───────────────────────────────────────────────────────────────

const BROAD_TOPICS = [
  "Политика", "Экономика", "Безопасность", "Международные отношения",
  "Общество", "Технологии", "Здоровье", "Культура", "Другое",
];

const ENTITY_TYPES = ["PER", "ORG", "LOC", "GPE"] as const;
type EntityType = typeof ENTITY_TYPES[number];

const QUALITY_CONFIG: Record<AnnotationQuality, { label: string; icon: typeof CheckCircle2; color: string }> = {
  useful:    { label: "annotation.useful",    icon: CheckCircle2, color: "text-green-600 dark:text-green-400" },
  noise:     { label: "annotation.noise",     icon: AlertCircle,  color: "text-amber-600 dark:text-amber-400" },
  duplicate: { label: "annotation.duplicate", icon: Copy,         color: "text-red-600   dark:text-red-400"   },
};

const STATUS_FILTERS = [
  { key: "",           labelKey: "annotation.filterAll" },
  { key: "pending",    labelKey: "annotation.filterPending" },
  { key: "completed",  labelKey: "annotation.filterCompleted" },
  { key: "skipped",    labelKey: "annotation.filterSkipped" },
] as const;

// ─── Sub-components ──────────────────────────────────────────────────────────

function TaskListItem({
  task, selected, onClick,
}: {
  task: AnnotationTask; selected: boolean; onClick: () => void;
}) {
  const { t } = useTranslation();
  const statusColor =
    task.status === "completed" ? "bg-green-500/20 text-green-700 dark:text-green-300"
    : task.status === "skipped"  ? "bg-muted text-muted-foreground"
    : "bg-primary/10 text-primary";

  return (
    <motion.button
      onClick={onClick}
      whileHover={{ x: 2 }}
      className={cn(
        "w-full text-left px-3 py-2.5 rounded-lg border transition-colors duration-150 flex items-start gap-3",
        selected
          ? "border-primary bg-primary/5"
          : "border-border hover:border-primary/40 hover:bg-accent",
      )}
    >
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-foreground truncate">{task.item.channel}</p>
        <p className="text-xs text-muted-foreground truncate mt-0.5 leading-snug">
          {task.item.text.slice(0, 90)}{task.item.text.length > 90 ? "…" : ""}
        </p>
        {task.label?.broad_topic && (
          <span className="inline-block mt-1 text-[10px] bg-primary/10 text-primary rounded px-1">
            {task.label.broad_topic}
          </span>
        )}
      </div>
      <div className="shrink-0 flex flex-col items-end gap-1">
        <span className={cn("text-[10px] font-semibold rounded px-1.5 py-0.5", statusColor)}>
          {task.status}
        </span>
        <span className="text-[10px] text-muted-foreground">
          {task.item.word_count} {t("annotation.wordCount")}
        </span>
      </div>
    </motion.button>
  );
}

function MessageCard({ task }: { task: AnnotationTask }) {
  const { t } = useTranslation();
  const date = task.item.message_date
    ? format(new Date(task.item.message_date), "d MMM yyyy HH:mm", { locale: ru })
    : "";

  return (
    <div className="bg-muted/40 rounded-xl border border-border p-4 space-y-2">
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span className="font-semibold text-foreground">@{task.item.channel}</span>
        <span>{date}</span>
        <span>{task.item.word_count} {t("annotation.wordCount")}</span>
        {task.item.language && <Badge variant="outline" className="text-[10px]">{task.item.language}</Badge>}
        {task.item.auto_topic_label && (
          <span className="text-[10px] bg-secondary text-secondary-foreground rounded px-1.5 py-0.5">
            {t("annotation.autoTopic")}: {task.item.auto_topic_label}
          </span>
        )}
      </div>
      <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">
        {task.item.text}
      </p>
    </div>
  );
}

// ─── Entities tag-input ───────────────────────────────────────────────────────

function EntitiesInput({
  value,
  onChange,
}: {
  value: Array<{ text: string; type: string }>;
  onChange: (v: Array<{ text: string; type: string }>) => void;
}) {
  const [inputText, setInputText] = useState("");
  const [inputType, setInputType] = useState<EntityType>("PER");
  const inputRef = useRef<HTMLInputElement>(null);

  const add = () => {
    const text = inputText.trim();
    if (!text) return;
    onChange([...value, { text, type: inputType }]);
    setInputText("");
    inputRef.current?.focus();
  };

  const remove = (idx: number) => onChange(value.filter((_, i) => i !== idx));

  const typeColor: Record<EntityType, string> = {
    PER: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
    ORG: "bg-purple-500/15 text-purple-700 dark:text-purple-300",
    LOC: "bg-green-500/15 text-green-700 dark:text-green-300",
    GPE: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  };

  return (
    <div className="space-y-2">
      <div className="flex gap-1.5">
        <input
          ref={inputRef}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder="Имя сущности..."
          className="flex-1 text-xs bg-background border border-border rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <select
          value={inputType}
          onChange={(e) => setInputType(e.target.value as EntityType)}
          className="text-xs bg-background border border-border rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {ENTITY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <button
          type="button"
          onClick={add}
          disabled={!inputText.trim()}
          className="px-2 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 disabled:opacity-40 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {value.map((ent, i) => (
            <span
              key={i}
              className={cn(
                "inline-flex items-center gap-1 text-[10px] font-medium rounded-full px-2 py-0.5",
                typeColor[ent.type as EntityType] ?? "bg-muted text-muted-foreground",
              )}
            >
              {ent.text}
              <span className="opacity-60">{ent.type}</span>
              <button onClick={() => remove(i)} className="ml-0.5 hover:opacity-70">
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Topic combobox ───────────────────────────────────────────────────────────

function TopicCombobox({
  value,
  onChange,
  existingTopics,
}: {
  value: string;
  onChange: (v: string) => void;
  existingTopics: string[];
}) {
  const listId = "annotation-topics-datalist";
  const allTopics = [...new Set([...BROAD_TOPICS, ...existingTopics])];

  return (
    <>
      <input
        list={listId}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Начните вводить или выберите тему..."
        className="w-full text-sm bg-background border border-border rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
      />
      <datalist id={listId}>
        {allTopics.map((t) => <option key={t} value={t} />)}
      </datalist>
    </>
  );
}

// ─── AnnotationForm ───────────────────────────────────────────────────────────

function AnnotationForm({
  task, userId, username, onDone, existingTopics,
}: {
  task: AnnotationTask;
  userId: string;
  username: string;
  onDone: () => void;
  existingTopics: string[];
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [broadTopic, setBroadTopic] = useState(task.label?.broad_topic ?? "");
  const [storyline, setStoryline] = useState(task.label?.storyline ?? "");
  const [isNew, setIsNew] = useState(task.label?.is_new_storyline ?? false);
  const [quality, setQuality] = useState<AnnotationQuality>(task.label?.quality ?? "useful");
  const [sentiment, setSentiment] = useState<string>(task.label?.sentiment ?? "");
  const [entities, setEntities] = useState<Array<{ text: string; type: string }>>(
    task.label?.entities ?? []
  );
  const [comment, setComment] = useState(task.label?.comment ?? "");
  const [confidence, setConfidence] = useState(task.label?.annotator_confidence ?? 1.0);
  const [submitted, setSubmitted] = useState(false);

  const submitMutation = useMutation({
    mutationFn: () =>
      api.submitLabel(task.id, {
        user_id: userId,
        username,
        broad_topic: broadTopic || null,
        storyline: storyline || null,
        is_new_storyline: isNew,
        quality,
        sentiment: sentiment || null,
        entities,
        comment: comment || null,
        annotator_confidence: confidence,
      }),
    onSuccess: () => {
      setSubmitted(true);
      queryClient.invalidateQueries({ queryKey: ["annotationTasks"] });
      queryClient.invalidateQueries({ queryKey: ["annotationStats"] });
      queryClient.invalidateQueries({ queryKey: ["annotationTopics"] });
      setTimeout(() => { setSubmitted(false); onDone(); }, 600);
    },
  });

  const skipMutation = useMutation({
    mutationFn: () => api.skipTask(task.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["annotationTasks"] });
      onDone();
    },
  });

  const busy = submitMutation.isPending || skipMutation.isPending;

  const sentimentConfig = [
    { key: "positive", label: "Позитив", icon: ThumbsUp, color: "text-green-600 dark:text-green-400" },
    { key: "neutral",  label: "Нейтрал", icon: Minus,    color: "text-muted-foreground" },
    { key: "negative", label: "Негатив", icon: ThumbsDown, color: "text-red-600 dark:text-red-400" },
  ] as const;

  return (
    <div className="space-y-4">
      {/* Broad topic combobox */}
      <div>
        <label className="block text-xs font-semibold text-muted-foreground mb-1.5">
          {t("annotation.broadTopic")}
        </label>
        <TopicCombobox
          value={broadTopic}
          onChange={setBroadTopic}
          existingTopics={existingTopics}
        />
      </div>

      {/* Storyline */}
      <div>
        <label className="block text-xs font-semibold text-muted-foreground mb-1.5">
          {t("annotation.storyline")}
        </label>
        <input
          type="text"
          value={storyline}
          onChange={(e) => setStoryline(e.target.value)}
          placeholder="Конкретный сюжет или событие..."
          className="w-full text-sm bg-background border border-border rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* New storyline toggle */}
      <div className="flex items-center gap-2">
        <button
          role="switch"
          aria-checked={isNew}
          onClick={() => setIsNew(!isNew)}
          className={cn(
            "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
            isNew ? "bg-primary" : "bg-muted",
          )}
        >
          <span
            className={cn(
              "inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform",
              isNew ? "translate-x-4" : "translate-x-0.5",
            )}
          />
        </button>
        <span className="text-xs text-foreground">{t("annotation.isNewStoryline")}</span>
      </div>

      {/* Sentiment */}
      <div>
        <label className="block text-xs font-semibold text-muted-foreground mb-1.5">
          Тональность
        </label>
        <div className="flex gap-2">
          {sentimentConfig.map(({ key, label, icon: Icon, color }) => (
            <button
              key={key}
              onClick={() => setSentiment(sentiment === key ? "" : key)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
                sentiment === key
                  ? `border-current ${color} bg-current/10`
                  : "border-border text-muted-foreground hover:border-primary/40",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Entities */}
      <div>
        <label className="block text-xs font-semibold text-muted-foreground mb-1.5">
          Сущности (PER/ORG/LOC/GPE)
        </label>
        <EntitiesInput value={entities} onChange={setEntities} />
      </div>

      {/* Quality */}
      <div>
        <label className="block text-xs font-semibold text-muted-foreground mb-1.5">
          {t("annotation.quality")}
        </label>
        <div className="flex gap-2">
          {(Object.entries(QUALITY_CONFIG) as [AnnotationQuality, typeof QUALITY_CONFIG[AnnotationQuality]][]).map(
            ([key, cfg]) => {
              const Icon = cfg.icon;
              return (
                <button
                  key={key}
                  onClick={() => setQuality(key)}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
                    quality === key
                      ? `border-current ${cfg.color} bg-current/10`
                      : "border-border text-muted-foreground hover:border-primary/40",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {t(cfg.label as Parameters<typeof t>[0])}
                </button>
              );
            }
          )}
        </div>
      </div>

      {/* Confidence */}
      <div>
        <label className="block text-xs font-semibold text-muted-foreground mb-1.5">
          {t("annotation.confidence")}: <span className="text-foreground">{confidence.toFixed(2)}</span>
        </label>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={confidence}
          onChange={(e) => setConfidence(parseFloat(e.target.value))}
          className="w-full accent-primary"
        />
        <div className="flex justify-between text-[10px] text-muted-foreground mt-0.5">
          <span>Сомневаюсь</span>
          <span>Уверен</span>
        </div>
      </div>

      {/* Comment */}
      <div>
        <label className="block text-xs font-semibold text-muted-foreground mb-1.5">
          {t("annotation.comment")}
        </label>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={2}
          placeholder="Необязательный комментарий..."
          className="w-full text-sm bg-background border border-border rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary resize-none"
        />
      </div>

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={() => submitMutation.mutate()}
          disabled={busy || submitted}
          className={cn(
            "flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-semibold transition-all",
            submitted
              ? "bg-green-500 text-white"
              : "bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50",
          )}
        >
          {submitted ? (
            <><CheckCircle2 className="h-4 w-4" />{t("annotation.submitted")}</>
          ) : submitMutation.isPending ? (
            <><Loader2 className="h-4 w-4 animate-spin" />{t("annotation.submit")}</>
          ) : (
            <><CheckCircle2 className="h-4 w-4" />{t("annotation.submit")}</>
          )}
        </button>
        <button
          onClick={() => skipMutation.mutate()}
          disabled={busy}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium border border-border text-muted-foreground hover:text-foreground hover:border-primary/40 transition-all disabled:opacity-50"
        >
          <SkipForward className="h-4 w-4" />
          {t("annotation.skip")}
        </button>
      </div>

      {submitMutation.isError && (
        <p className="text-xs text-destructive">
          {submitMutation.error instanceof Error ? submitMutation.error.message : "Ошибка сохранения."}
        </p>
      )}
    </div>
  );
}

function StatsPanel({ datasetId }: { datasetId?: string }) {
  const { data: stats } = useAnnotationStats(datasetId);
  const firstStat = stats?.[0];
  if (!firstStat) return null;

  const pct = Math.round(firstStat.annotation_progress * 100);

  return (
    <div className="rounded-xl border border-border p-4 space-y-3">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <BarChart2 className="h-4 w-4 text-primary" />
        {firstStat.dataset_version_name}
      </div>
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>Размечено {firstStat.annotated_items} / {firstStat.total_items}</span>
          <span>{pct}%</span>
        </div>
        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className="h-full bg-primary rounded-full transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      <div className="flex gap-2 text-[11px]">
        <span className="text-green-600 dark:text-green-400">✓ {firstStat.quality_distribution.useful} полезных</span>
        <span className="text-amber-500">⚠ {firstStat.quality_distribution.noise} шум</span>
        <span className="text-red-500">⊘ {firstStat.quality_distribution.duplicate} дубль</span>
      </div>
    </div>
  );
}

// ─── ChannelMultiSelect ───────────────────────────────────────────────────────

function ChannelMultiSelect({
  selected,
  onChange,
  channels,
}: {
  selected: string[];
  onChange: (v: string[]) => void;
  channels: string[];
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = channels.filter((ch) =>
    ch.toLowerCase().includes(search.toLowerCase())
  );

  const toggle = (ch: string) =>
    onChange(selected.includes(ch) ? selected.filter((c) => c !== ch) : [...selected, ch]);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between text-xs bg-background border border-border rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary text-left"
      >
        <span className={selected.length ? "text-foreground" : "text-muted-foreground"}>
          {selected.length === 0
            ? "Все каналы"
            : selected.length === 1
            ? selected[0]
            : `${selected.length} каналов выбрано`}
        </span>
        <ChevronRight className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", open && "rotate-90")} />
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full bg-background border border-border rounded-lg shadow-lg p-2 space-y-1 max-h-48 overflow-hidden flex flex-col">
          <input
            autoFocus
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск канала..."
            className="text-xs bg-muted rounded px-2 py-1 focus:outline-none border border-border"
          />
          <div className="flex gap-1.5 text-[10px]">
            <button
              onClick={() => onChange(channels)}
              className="text-primary hover:underline"
            >Все</button>
            <button
              onClick={() => onChange([])}
              className="text-muted-foreground hover:underline"
            >Сбросить</button>
          </div>
          <div className="overflow-y-auto space-y-0.5">
            {filtered.map((ch) => (
              <label key={ch} className="flex items-center gap-2 px-1 py-0.5 rounded hover:bg-muted cursor-pointer">
                <input
                  type="checkbox"
                  checked={selected.includes(ch)}
                  onChange={() => toggle(ch)}
                  className="accent-primary h-3 w-3"
                />
                <span className="text-xs truncate">{ch}</span>
              </label>
            ))}
            {filtered.length === 0 && (
              <p className="text-[10px] text-muted-foreground text-center py-2">Не найдено</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── BuildDatasetForm ─────────────────────────────────────────────────────────

function BuildDatasetForm({ onClose, onBuilt }: { onClose: () => void; onBuilt: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: allChannels = [] } = useChannels();

  const [name, setName] = useState("ru-telegram-topics-v1");
  const [desc, setDesc] = useState("");
  const [start, setStart] = useState(() => {
    const now = new Date();
    now.setDate(now.getDate() - 180);
    return now.toISOString().slice(0, 10);
  });
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [minWords, setMinWords] = useState(5);
  const [dedup, setDedup] = useState("event_id");
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);

  const buildMutation = useMutation({
    mutationFn: () =>
      api.buildDataset({
        name,
        description: desc || undefined,
        window_start: new Date(start).toISOString(),
        window_end: new Date(end + "T23:59:59").toISOString(),
        channels: selectedChannels.length > 0 ? selectedChannels : undefined,
        min_word_count: minWords,
        dedup_strategy: dedup,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["datasets"] });
      queryClient.invalidateQueries({ queryKey: ["annotationTasks"] });
      queryClient.invalidateQueries({ queryKey: ["annotationStats"] });
      onBuilt();
      onClose();
    },
  });

  const field = "w-full text-xs bg-background border border-border rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary";

  return (
    <div className="rounded-xl border border-primary/40 bg-primary/5 p-3 space-y-2.5">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold text-foreground">{t("annotation.buildDataset")}</span>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div>
        <label className="block text-[10px] text-muted-foreground mb-1">{t("annotation.datasetName")} *</label>
        <input className={field} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <label className="block text-[10px] text-muted-foreground mb-1">{t("annotation.datasetDesc")}</label>
        <input className={field} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Необязательно" />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[10px] text-muted-foreground mb-1">{t("annotation.windowStart")} *</label>
          <input type="date" className={field} value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div>
          <label className="block text-[10px] text-muted-foreground mb-1">{t("annotation.windowEnd")} *</label>
          <input type="date" className={field} value={end} onChange={(e) => setEnd(e.target.value)} />
        </div>
      </div>

      {/* Channel selector */}
      <div>
        <label className="block text-[10px] text-muted-foreground mb-1">Каналы (пусто = все)</label>
        <ChannelMultiSelect
          selected={selectedChannels}
          onChange={setSelectedChannels}
          channels={allChannels}
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[10px] text-muted-foreground mb-1">{t("annotation.minWords")}</label>
          <input type="number" min={1} max={50} className={field} value={minWords} onChange={(e) => setMinWords(Number(e.target.value))} />
        </div>
        <div>
          <label className="block text-[10px] text-muted-foreground mb-1">{t("annotation.dedup")}</label>
          <select className={field} value={dedup} onChange={(e) => setDedup(e.target.value)}>
            <option value="event_id">event_id</option>
            <option value="text_hash">text_hash</option>
            <option value="none">none</option>
          </select>
        </div>
      </div>

      {buildMutation.isError && (
        <p className="text-[10px] text-destructive">
          {buildMutation.error instanceof Error ? buildMutation.error.message : "Ошибка сборки. Проверьте параметры."}
        </p>
      )}

      <button
        onClick={() => buildMutation.mutate()}
        disabled={buildMutation.isPending || !name || !start || !end}
        className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-all"
      >
        {buildMutation.isPending ? (
          <><Loader2 className="h-3.5 w-3.5 animate-spin" />{t("annotation.building")}</>
        ) : (
          t("annotation.buildBtn")
        )}
      </button>
    </div>
  );
}

function DatasetsPanel({
  datasets, onRequestBuild, onAnnotate,
}: {
  datasets: DatasetVersion[];
  onRequestBuild: () => void;
  onAnnotate: (id: string) => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="space-y-2">
      <button
        onClick={onRequestBuild}
        className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg border border-dashed border-primary/40 text-xs text-primary hover:bg-primary/5 transition-colors"
      >
        <Plus className="h-3.5 w-3.5" />
        {t("annotation.buildDataset")}
      </button>

      {datasets.length === 0 && (
        <p className="text-xs text-muted-foreground text-center py-4">
          Датасеты не найдены. Нажмите «{t("annotation.buildDataset")}» выше.
        </p>
      )}

      {datasets.map((ds) => (
        <div key={ds.id} className="rounded-lg border border-border px-3 py-2.5 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-foreground">{ds.name}</span>
            <span className={cn(
              "text-[10px] font-semibold rounded px-1.5 py-0.5",
              ds.status === "ready" ? "bg-green-500/15 text-green-700 dark:text-green-300"
              : ds.status === "building" ? "bg-amber-500/15 text-amber-600"
              : "bg-muted text-muted-foreground",
            )}>
              {ds.status}
            </span>
          </div>
          <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
            <span>{ds.total_items} сообщений</span>
            <span>{Math.round(ds.annotation_progress * 100)}% размечено</span>
            {ds.channels.length > 0 && (
              <span title={ds.channels.join(", ")}>{ds.channels.length} каналов</span>
            )}
          </div>
          {ds.status === "ready" && (
            <div className="space-y-1.5">
              <button
                onClick={() => onAnnotate(ds.id)}
                className="w-full text-[11px] font-semibold py-1 rounded-md bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
              >
                Разметить →
              </button>
              <div className="flex gap-1.5 flex-wrap">
                {(["csv", "jsonl", "octis", "huggingface"] as const).map((fmt) => (
                  <a
                    key={fmt}
                    href={api.getDatasetExportUrl(ds.id, fmt)}
                    download
                    className="inline-flex items-center gap-1 text-[10px] border border-border rounded px-1.5 py-0.5 text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors"
                  >
                    <Download className="h-2.5 w-2.5" />
                    {fmt.toUpperCase()}
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function AnnotationTopicsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();

  const [statusFilter, setStatusFilter] = useState("");
  const [datasetFilter, setDatasetFilter] = useState("");
  const [selectedTask, setSelectedTask] = useState<AnnotationTask | null>(null);
  const [activeTab, setActiveTab] = useState<"tasks" | "datasets">("tasks");
  const [showBuildForm, setShowBuildForm] = useState(false);

  const { data: datasets = [] } = useDatasets();
  const { data: existingTopics = [] } = useAnnotationTopics();

  const { data: tasks = [], isLoading: tasksLoading, refetch } = useAnnotationTasks({
    status: statusFilter || undefined,
    dataset_id: datasetFilter || undefined,
    limit: 50,
  });

  const selectedDatasetId = datasetFilter
    || selectedTask?.item.dataset_version_id
    || datasets[0]?.id;

  const handleDone = useCallback(() => {
    const currentIdx = tasks.findIndex((t) => t.id === selectedTask?.id);
    const next = tasks.slice(currentIdx + 1).find((t) => t.status === "pending")
      ?? tasks.slice(0, currentIdx).find((t) => t.status === "pending");
    setSelectedTask(next ?? null);
  }, [tasks, selectedTask]);

  return (
    <>
      <Header title={t("annotation.title")} />
      <PageTransition>
        <div className="flex h-[calc(100vh-4rem)] overflow-hidden">
          {/* Left panel — task list */}
          <div className="w-80 shrink-0 border-r border-border flex flex-col bg-sidebar">
            {/* Tabs */}
            <div className="flex border-b border-border">
              {(["tasks", "datasets"] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={cn(
                    "flex-1 py-2.5 text-xs font-semibold transition-colors",
                    activeTab === tab
                      ? "border-b-2 border-primary text-primary"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {tab === "tasks" ? t("annotation.tasks") : t("annotation.datasets")}
                </button>
              ))}
            </div>

            {activeTab === "tasks" && (
              <>
                {/* Filters */}
                <div className="px-3 pt-3 pb-2 space-y-2">
                  {/* Dataset selector */}
                  <select
                    value={datasetFilter}
                    onChange={(e) => { setDatasetFilter(e.target.value); setSelectedTask(null); }}
                    className="w-full text-xs bg-background border border-border rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value="">Все датасеты</option>
                    {datasets.map((ds) => (
                      <option key={ds.id} value={ds.id}>{ds.name}</option>
                    ))}
                  </select>
                  {/* Status filter + refresh */}
                  <div className="flex gap-2 items-center">
                    <select
                      value={statusFilter}
                      onChange={(e) => setStatusFilter(e.target.value)}
                      className="flex-1 text-xs bg-background border border-border rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                    >
                      {STATUS_FILTERS.map((f) => (
                        <option key={f.key} value={f.key}>{t(f.labelKey as Parameters<typeof t>[0])}</option>
                      ))}
                    </select>
                    <button
                      onClick={() => refetch()}
                      className="p-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5">
                  {tasksLoading ? (
                    <div className="flex justify-center py-8">
                      <Loader2 className="h-5 w-5 text-primary animate-spin" />
                    </div>
                  ) : tasks.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-8">
                      {t("annotation.noTasks")}
                    </p>
                  ) : (
                    tasks.map((task) => (
                      <TaskListItem
                        key={task.id}
                        task={task}
                        selected={selectedTask?.id === task.id}
                        onClick={() => setSelectedTask(task)}
                      />
                    ))
                  )}
                </div>

                {/* Stats */}
                <div className="border-t border-border p-3">
                  <StatsPanel datasetId={selectedDatasetId} />
                </div>
              </>
            )}

            {activeTab === "datasets" && (
              <div className="flex-1 overflow-y-auto p-3 space-y-3">
                {showBuildForm && (
                  <BuildDatasetForm
                    onClose={() => setShowBuildForm(false)}
                    onBuilt={() => setShowBuildForm(false)}
                  />
                )}
                <DatasetsPanel
                  datasets={datasets}
                  onRequestBuild={() => setShowBuildForm(true)}
                  onAnnotate={(id) => { setDatasetFilter(id); setActiveTab("tasks"); setSelectedTask(null); }}
                />
              </div>
            )}
          </div>

          {/* Right panel — annotation workspace */}
          <div className="flex-1 overflow-y-auto p-6">
            <AnimatePresence mode="wait">
              {!selectedTask ? (
                <motion.div
                  key="empty"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex flex-col items-center justify-center h-full text-muted-foreground gap-4"
                >
                  <Tag className="h-12 w-12 opacity-20" />
                  <p className="text-sm">{t("annotation.selectTask")}</p>
                  {tasks.filter((t) => t.status === "pending").length > 0 && (
                    <button
                      onClick={() => setSelectedTask(tasks.find((t) => t.status === "pending") ?? null)}
                      className="flex items-center gap-1.5 text-sm text-primary hover:underline"
                    >
                      Начать с первой задачи <ChevronRight className="h-4 w-4" />
                    </button>
                  )}
                </motion.div>
              ) : (
                <motion.div
                  key={selectedTask.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                  className="max-w-2xl mx-auto space-y-5"
                >
                  {/* Task header */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground font-mono">
                        {selectedTask.id.slice(0, 8)}…
                      </span>
                      <Badge variant="outline" className="text-[10px]">
                        {selectedTask.item.split}
                      </Badge>
                    </div>
                    <a
                      href={`/analytics/annotation/guidelines`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <BookOpen className="h-3.5 w-3.5" />
                      Инструкция
                    </a>
                  </div>

                  {/* Message card */}
                  <MessageCard task={selectedTask} />

                  {/* Annotation form */}
                  <Card>
                    <h3 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
                      <Tag className="h-4 w-4 text-primary" />
                      Разметка
                    </h3>
                    {user ? (
                      <AnnotationForm
                        key={selectedTask.id}
                        task={selectedTask}
                        userId={user.id}
                        username={user.username}
                        onDone={handleDone}
                        existingTopics={existingTopics}
                      />
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Войдите в систему для разметки.
                      </p>
                    )}
                  </Card>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </PageTransition>
    </>
  );
}
