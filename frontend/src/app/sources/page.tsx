"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  CircleAlert,
  ExternalLink,
  Link as LinkIcon,
  Loader2,
  Radio,
} from "lucide-react";

import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AuthApiError, authApi } from "@/lib/auth";
import { cn, formatNumber } from "@/lib/utils";
import type { UserTelegramChannel, UserSourceStatus } from "@/types";

const MIN_SOURCE_DATE = "2026-01-01";

const STATUS_META: Record<
  UserSourceStatus,
  { label: string; className: string; description: string }
> = {
  validating: {
    label: "Validating",
    className: "bg-amber-500/10 text-amber-600 border border-amber-500/20",
    description: "Collector has picked up the request and is validating the Telegram channel.",
  },
  validation_failed: {
    label: "Validation failed",
    className: "bg-destructive/10 text-destructive border border-destructive/20",
    description: "Collector could not access the Telegram channel.",
  },
  live_enabled: {
    label: "Live enabled",
    className: "bg-sky-500/10 text-sky-600 border border-sky-500/20",
    description: "Live collection is on. Historical backfill has not started yet.",
  },
  backfilling: {
    label: "Backfilling",
    className: "bg-primary/10 text-primary border border-primary/20",
    description: "Historical days are loading newest-first.",
  },
  ready: {
    label: "Ready",
    className: "bg-positive/10 text-positive border border-positive/20",
    description: "The source is validated and current backfill work is complete.",
  },
};

function describeSubmitError(error: unknown): string {
  if (error instanceof AuthApiError) {
    switch (error.code) {
      case "duplicate":
        return `Channel already exists: ${String(error.meta?.channel_name ?? "")}`.trim();
      case "validation_pending":
        return "This channel is already waiting for validation.";
      case "validation_failed":
        return error.message || "Validation failed for this channel.";
      case "date_before_limit":
        return "Start date must be on or after 2026-01-01.";
      case "invalid_link_or_username":
        return "Enter a public Telegram username or t.me link.";
      default:
        return error.message;
    }
  }
  return error instanceof Error ? error.message : "Request failed";
}

export default function SourcesPage() {
  const queryClient = useQueryClient();
  const [channelInput, setChannelInput] = useState("");
  const [startDate, setStartDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [submitError, setSubmitError] = useState<string | null>(null);

  const channelsQuery = useQuery<UserTelegramChannel[]>({
    queryKey: ["telegram-sources"],
    queryFn: () => authApi.getTelegramChannels(),
    refetchInterval: 5000,
  });

  const addChannelMutation = useMutation({
    mutationFn: () => authApi.addTelegramChannel(channelInput.trim(), startDate),
    onSuccess: async () => {
      setSubmitError(null);
      setChannelInput("");
      await queryClient.invalidateQueries({ queryKey: ["telegram-sources"] });
    },
    onError: (error) => {
      setSubmitError(describeSubmitError(error));
    },
  });

  return (
    <>
      <Header title="Sources" />
      <PageTransition>
        <div className="p-6 space-y-6">
          <Card className="relative overflow-hidden">
            <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary via-sky-500 to-emerald-500" />
            <CardHeader className="relative">
              <CardTitle className="flex items-center gap-2 text-base">
                <Radio className="w-4 h-4 text-primary" />
                Add Telegram channel
              </CardTitle>
              <CardDescription>
                Public Telegram channels only. Historical lower bound is 2026-01-01.
              </CardDescription>
            </CardHeader>

            <div className="grid gap-4 md:grid-cols-[1.5fr_0.9fr_auto]">
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  Username or link
                </span>
                <div className="relative">
                  <LinkIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <input
                    value={channelInput}
                    onChange={(event) => setChannelInput(event.target.value)}
                    placeholder="@channel_name or https://t.me/channel_name"
                    className="w-full rounded-xl border border-border bg-muted pl-10 pr-3 py-3 text-sm text-foreground outline-none transition-all focus:ring-2 focus:ring-primary/30"
                  />
                </div>
              </label>

              <label className="space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  Start date
                </span>
                <div className="relative">
                  <CalendarDays className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <input
                    type="date"
                    min={MIN_SOURCE_DATE}
                    value={startDate}
                    onChange={(event) => setStartDate(event.target.value)}
                    className="w-full rounded-xl border border-border bg-muted pl-10 pr-3 py-3 text-sm text-foreground outline-none transition-all focus:ring-2 focus:ring-primary/30"
                  />
                </div>
              </label>

              <div className="flex items-end">
                <button
                  onClick={() => addChannelMutation.mutate()}
                  disabled={!channelInput.trim() || addChannelMutation.isPending}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {addChannelMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : null}
                  Submit
                </button>
              </div>
            </div>

            <div className="mt-4 rounded-xl border border-border/70 bg-muted/40 p-3 text-xs text-muted-foreground">
              New channels appear here immediately with a <span className="font-semibold text-foreground">validating</span> state.
              Once the collector emits the first messages, use the feed link to open
              <span className="font-semibold text-foreground"> /feed </span>
              already filtered by channel.
            </div>

            {submitError ? (
              <div className="mt-4 flex items-start gap-2 rounded-xl border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive">
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{submitError}</span>
              </div>
            ) : null}
          </Card>

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-foreground">Your channels</h2>
                <p className="text-xs text-muted-foreground">
                  Live registry state from the authenticated source API.
                </p>
              </div>
              {channelsQuery.isFetching ? (
                <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Updating
                </div>
              ) : null}
            </div>

            {channelsQuery.isLoading ? (
              <Card className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 animate-spin text-primary" />
              </Card>
            ) : channelsQuery.isError ? (
              <Card className="border-destructive/20 bg-destructive/10 text-sm text-destructive">
                {describeSubmitError(channelsQuery.error)}
              </Card>
            ) : channelsQuery.data && channelsQuery.data.length > 0 ? (
              <div className="grid gap-4">
                {channelsQuery.data.map((channel) => {
                  const meta = STATUS_META[channel.status];
                  const totalDays = channel.backfill_total_days;
                  const accountedDays =
                    channel.backfill_completed_days + channel.backfill_failed_days;

                  return (
                    <Card key={channel.channel_name} className="space-y-4">
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="space-y-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="text-base font-semibold text-foreground">
                              {channel.channel_name}
                            </h3>
                            <Badge className={cn("border", meta.className)}>
                              {meta.label}
                            </Badge>
                            {channel.telegram_url ? (
                              <a
                                href={channel.telegram_url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
                              >
                                Telegram
                                <ExternalLink className="w-3 h-3" />
                              </a>
                            ) : null}
                          </div>
                          <p className="text-sm text-muted-foreground">{meta.description}</p>
                          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                            <span>Requested from {channel.requested_start_date ?? MIN_SOURCE_DATE}</span>
                            <span>Lower bound {channel.historical_limit_date}</span>
                            <span>Messages loaded {formatNumber(channel.raw_message_count)}</span>
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          {channel.feed_path && channel.first_message_available ? (
                            <Link
                              href={channel.feed_path}
                              className="inline-flex items-center gap-2 rounded-xl border border-border bg-muted px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
                            >
                              Open in feed
                            </Link>
                          ) : (
                            <div className="inline-flex items-center rounded-xl border border-border/70 px-3 py-2 text-sm text-muted-foreground">
                              Waiting for first data
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="grid gap-3 md:grid-cols-4">
                        <div className="rounded-xl border border-border/70 bg-muted/40 p-3">
                          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                            Progress
                          </p>
                          <p className="mt-1 text-lg font-semibold text-foreground">
                            {totalDays > 0 ? `${channel.backfill_completed_days}/${totalDays}` : "Live only"}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Failed {channel.backfill_failed_days}
                          </p>
                        </div>

                        <div className="rounded-xl border border-border/70 bg-muted/40 p-3">
                          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                            Queue
                          </p>
                          <p className="mt-1 text-lg font-semibold text-foreground">
                            {channel.backfill_pending_days}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Running {channel.backfill_running_days} | Retrying {channel.backfill_retrying_days}
                          </p>
                        </div>

                        <div className="rounded-xl border border-border/70 bg-muted/40 p-3">
                          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                            Last completed day
                          </p>
                          <p className="mt-1 text-lg font-semibold text-foreground">
                            {channel.backfill_last_completed_date ?? "None"}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Accounted days {accountedDays}
                          </p>
                        </div>

                        <div className="rounded-xl border border-border/70 bg-muted/40 p-3">
                          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                            First data
                          </p>
                          <p className="mt-1 text-lg font-semibold text-foreground">
                            {channel.first_message_at ? "Available" : "Pending"}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {channel.first_message_at ?? "Collector has not emitted persisted data yet."}
                          </p>
                        </div>
                      </div>

                      {channel.validation_error ? (
                        <div className="rounded-xl border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive">
                          {channel.validation_error}
                        </div>
                      ) : null}
                    </Card>
                  );
                })}
              </div>
            ) : (
              <Card className="text-sm text-muted-foreground">
                No user-added Telegram channels yet.
              </Card>
            )}
          </div>
        </div>
      </PageTransition>
    </>
  );
}
