"use client";

import { useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  GitMerge,
  Loader2,
  Pencil,
  RefreshCw,
  Scissors,
  Search,
  ShieldQuestion,
  Trash2,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MessageCard } from "@/components/feed/message-card";
import { useAuth } from "@/components/auth/auth-provider";
import { useTopicReviewTask, useTopicReviewTasks } from "@/lib/use-data";
import { api } from "@/lib/api";
import { cn, entityTypeColor } from "@/lib/utils";
import type { TopicReviewActionRequest, TopicReviewTask } from "@/types";

const REASON_LABELS: Record<string, string> = {
  new_topic: "Новая тема",
  low_confidence: "Низкая уверенность",
  high_outlier_ratio: "Много выбросов",
  history_conflict: "Конфликт с историей",
  rapid_growth: "Быстрый рост",
  manual_request: "Ручная проверка",
};

function ActionButton({
  icon,
  label,
  onClick,
  active,
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-9 items-center gap-2 border border-border px-3 text-sm transition-colors hover:bg-accent",
        active && "border-primary bg-primary/10 text-primary"
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function TaskList({
  tasks,
  selectedId,
  onSelect,
}: {
  tasks: TopicReviewTask[];
  selectedId?: string;
  onSelect: (task: TopicReviewTask) => void;
}) {
  return (
    <div className="space-y-2">
      {tasks.map((task) => (
        <button
          key={task.id}
          type="button"
          onClick={() => onSelect(task)}
          className={cn(
            "w-full border border-border bg-card p-3 text-left transition-colors hover:bg-accent",
            selectedId === task.id && "border-primary bg-primary/10"
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-foreground">
                {task.topic?.label || task.active_label || task.cluster_id}
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">{task.cluster_id}</div>
            </div>
            <span className="shrink-0 rounded bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              P{task.priority}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap gap-1">
            <Badge>{REASON_LABELS[task.reason] || task.reason}</Badge>
            {task.label_source && <Badge>{task.label_source}</Badge>}
          </div>
        </button>
      ))}
    </div>
  );
}

export default function TopicReviewPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("pending");
  const { data: tasks = [], isLoading, isFetching } = useTopicReviewTasks(status);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [action, setAction] = useState<"confirm" | "rename" | "merge" | "split" | "reject" | "uncertain">("confirm");
  const [label, setLabel] = useState("");
  const [targetClusterId, setTargetClusterId] = useState("");
  const [childLabels, setChildLabels] = useState("");
  const [comment, setComment] = useState("");

  const selectedListItem = useMemo(
    () => tasks.find((task) => task.id === selectedId) || tasks[0] || null,
    [selectedId, tasks]
  );
  const activeId = selectedListItem?.id ?? null;
  const { data: selectedDetail, isLoading: isDetailLoading } = useTopicReviewTask(activeId);
  const selected = selectedDetail ?? selectedListItem;

  const mutation = useMutation({
    mutationFn: async () => {
      if (!selected) return;
      const base: TopicReviewActionRequest = {
        actor_user_id: user?.id,
        actor_username: user?.username,
        comment,
      };
      if (action === "confirm") {
        return api.confirmTopicReview(selected.id, { ...base, label: label || selected.topic?.label || selected.active_label || undefined, confidence: 1 });
      }
      if (action === "rename") {
        return api.renameTopicReview(selected.id, { ...base, label, confidence: 1 });
      }
      if (action === "merge") {
        return api.mergeTopicReview(selected.id, { ...base, target_cluster_id: targetClusterId, label: label || selected.topic?.label || undefined });
      }
      if (action === "split") {
        return api.splitTopicReview(selected.id, {
          ...base,
          child_labels: childLabels.split("\n").map((item) => item.trim()).filter(Boolean),
        });
      }
      if (action === "uncertain") {
        return api.rejectTopicReview(selected.id, { ...base, reason: "uncertain", label: label || selected.topic?.label || undefined });
      }
      return api.rejectTopicReview(selected.id, { ...base, reason: "noise", label: label || selected.topic?.label || undefined });
    },
    onSuccess: () => {
      setComment("");
      queryClient.invalidateQueries({ queryKey: ["topicReviewTasks"] });
      queryClient.invalidateQueries({ queryKey: ["topicReviewTask", activeId] });
      queryClient.invalidateQueries({ queryKey: ["topics"] });
    },
  });

  const topic = selected?.topic;

  return (
    <>
      <Header title="Проверка тем" />
      <PageTransition>
        <div className="space-y-5 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold text-foreground">Human-in-the-loop контур тематических кластеров</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Подтверждение, переименование, объединение, разделение и отклонение тем сохраняется в историю и попадает в датасет.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                className="h-9 border border-border bg-background px-3 text-sm outline-none"
              >
                <option value="pending">Ожидают</option>
                <option value="completed">Завершены</option>
                <option value="rejected">Отклонены</option>
                <option value="all">Все</option>
              </select>
              <button
                type="button"
                onClick={() => queryClient.invalidateQueries({ queryKey: ["topicReviewTasks"] })}
                className="inline-flex h-9 items-center gap-2 border border-border px-3 text-sm hover:bg-accent"
              >
                <RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} />
                Обновить
              </button>
            </div>
          </div>

          <div className="grid gap-5 xl:grid-cols-[360px_1fr]">
            <section>
              <div className="mb-3 flex items-center justify-between">
                <div className="text-sm text-muted-foreground">
                  {isLoading ? "Загрузка..." : `${tasks.length} задач`}
                </div>
              </div>
              {isLoading ? (
                <div className="flex min-h-[240px] items-center justify-center border border-border">
                  <Loader2 className="h-5 w-5 animate-spin text-primary" />
                </div>
              ) : tasks.length > 0 ? (
                <TaskList tasks={tasks} selectedId={selected?.id} onSelect={(task) => setSelectedId(task.id)} />
              ) : (
                <div className="border border-dashed border-border p-6 text-sm text-muted-foreground">
                  Нет задач для выбранного статуса.
                </div>
              )}
            </section>

            {isDetailLoading ? (
              <div className="flex min-h-[360px] items-center justify-center border border-border">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
              </div>
            ) : selected && topic ? (
              <section className="space-y-5">
                <Card className="rounded-none">
                  <CardHeader>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <CardTitle>{topic.label}</CardTitle>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <Badge>{REASON_LABELS[selected.reason] || selected.reason}</Badge>
                          <Badge>{selected.status}</Badge>
                          {topic.review?.source && <Badge>{topic.review.source}</Badge>}
                        </div>
                      </div>
                      <Link href={`/topics/${encodeURIComponent(topic.cluster_id)}`} className="text-sm text-primary hover:underline">
                        Открыть тему
                      </Link>
                    </div>
                  </CardHeader>

                  <div className="grid gap-4 md:grid-cols-4">
                    <div className="border border-border p-3">
                      <div className="text-xs uppercase text-muted-foreground">Сообщения</div>
                      <div className="mt-1 text-lg font-semibold">{topic.message_count}</div>
                    </div>
                    <div className="border border-border p-3">
                      <div className="text-xs uppercase text-muted-foreground">Каналы</div>
                      <div className="mt-1 text-lg font-semibold">{topic.channel_count}</div>
                    </div>
                    <div className="border border-border p-3">
                      <div className="text-xs uppercase text-muted-foreground">Confidence</div>
                      <div className="mt-1 text-lg font-semibold">{topic.confidence_score?.toFixed(2) || "n/a"}</div>
                    </div>
                    <div className="border border-border p-3">
                      <div className="text-xs uppercase text-muted-foreground">Stability</div>
                      <div className="mt-1 text-lg font-semibold">{topic.stability_score?.toFixed(2) || "n/a"}</div>
                    </div>
                  </div>

                  <div className="mt-5 grid gap-5 lg:grid-cols-2">
                    <div>
                      <div className="text-xs font-medium uppercase text-muted-foreground">Ключевые слова</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {topic.top_keywords.length > 0 ? topic.top_keywords.map((keyword) => (
                          <Badge key={keyword}>{keyword}</Badge>
                        )) : <span className="text-sm text-muted-foreground">Нет ключевых слов</span>}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-medium uppercase text-muted-foreground">Сущности</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {topic.top_entities.length > 0 ? topic.top_entities.slice(0, 8).map((entity) => (
                          <Badge key={entity.id} variant="entity" color={entityTypeColor(entity.type)}>
                            {entity.text}
                          </Badge>
                        )) : <span className="text-sm text-muted-foreground">Нет сущностей</span>}
                      </div>
                    </div>
                  </div>
                </Card>

                <Card className="rounded-none">
                  <CardHeader>
                    <CardTitle>Решение аналитика</CardTitle>
                  </CardHeader>
                  <div className="space-y-4">
                    <div className="flex flex-wrap gap-2">
                      <ActionButton icon={<Check className="h-4 w-4" />} label="Подтвердить" active={action === "confirm"} onClick={() => setAction("confirm")} />
                      <ActionButton icon={<Pencil className="h-4 w-4" />} label="Переименовать" active={action === "rename"} onClick={() => setAction("rename")} />
                      <ActionButton icon={<GitMerge className="h-4 w-4" />} label="Объединить" active={action === "merge"} onClick={() => setAction("merge")} />
                      <ActionButton icon={<Scissors className="h-4 w-4" />} label="Разделить" active={action === "split"} onClick={() => setAction("split")} />
                      <ActionButton icon={<Trash2 className="h-4 w-4" />} label="Шум" active={action === "reject"} onClick={() => setAction("reject")} />
                      <ActionButton icon={<ShieldQuestion className="h-4 w-4" />} label="Сомнительно" active={action === "uncertain"} onClick={() => setAction("uncertain")} />
                    </div>

                    {(action === "confirm" || action === "rename" || action === "merge" || action === "uncertain") && (
                      <input
                        value={label}
                        onChange={(event) => setLabel(event.target.value)}
                        placeholder={topic.label}
                        className="h-10 w-full border border-border bg-background px-3 text-sm outline-none focus:border-primary"
                      />
                    )}
                    {action === "merge" && (
                      <input
                        value={targetClusterId}
                        onChange={(event) => setTargetClusterId(event.target.value)}
                        placeholder="ID целевой темы"
                        className="h-10 w-full border border-border bg-background px-3 text-sm outline-none focus:border-primary"
                      />
                    )}
                    {action === "split" && (
                      <textarea
                        value={childLabels}
                        onChange={(event) => setChildLabels(event.target.value)}
                        placeholder={"Дочерняя тема 1\nДочерняя тема 2"}
                        className="min-h-[96px] w-full border border-border bg-background p-3 text-sm outline-none focus:border-primary"
                      />
                    )}
                    <textarea
                      value={comment}
                      onChange={(event) => setComment(event.target.value)}
                      placeholder="Комментарий к решению"
                      className="min-h-[80px] w-full border border-border bg-background p-3 text-sm outline-none focus:border-primary"
                    />
                    {mutation.error && (
                      <div className="text-sm text-destructive">
                        {mutation.error instanceof Error ? mutation.error.message : "Ошибка сохранения"}
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => mutation.mutate()}
                      disabled={mutation.isPending}
                      className="inline-flex h-10 items-center gap-2 bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-60"
                    >
                      {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                      Сохранить решение
                    </button>
                  </div>
                </Card>

                <Card className="rounded-none">
                  <CardHeader>
                    <CardTitle>Репрезентативные сообщения</CardTitle>
                  </CardHeader>
                  <div className="space-y-3">
                    {topic.representative_messages.length > 0 ? topic.representative_messages.map((message, index) => (
                      <MessageCard key={message.event_id} message={message} index={index} />
                    )) : (
                      <div className="border border-dashed border-border p-6 text-sm text-muted-foreground">
                        Нет репрезентативных сообщений.
                      </div>
                    )}
                  </div>
                </Card>
              </section>
            ) : (
              <div className="flex min-h-[360px] items-center justify-center border border-dashed border-border text-sm text-muted-foreground">
                <Search className="mr-2 h-4 w-4" />
                Выберите тему для проверки.
              </div>
            )}
          </div>
        </div>
      </PageTransition>
    </>
  );
}
