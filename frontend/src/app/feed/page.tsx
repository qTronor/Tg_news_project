"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { MessageCard } from "@/components/feed/message-card";
import { useTranslation } from "@/lib/i18n";
import { useMessages, useTopics } from "@/lib/use-data";
import { useDemoContext } from "@/components/providers";
import { Search, Filter, Radio, Loader2, WifiOff } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

const sentiments = ["All", "Positive", "Neutral", "Negative"];

export default function FeedPage() {
  const { t } = useTranslation();
  const { isDemo } = useDemoContext();
  const searchParams = useSearchParams();
  const [search, setSearch] = useState("");
  const [channelFilter, setChannelFilter] = useState("All");
  const [topicFilter, setTopicFilter] = useState("All");
  const [sentimentFilter, setSentimentFilter] = useState("All");
  const [liveMode, setLiveMode] = useState(false);

  const filters = useMemo(() => ({
    channel: channelFilter !== "All" ? channelFilter : undefined,
    topic: topicFilter !== "All" ? topicFilter : undefined,
    sentiment: sentimentFilter !== "All" ? sentimentFilter : undefined,
    search: search || undefined,
  }), [search, channelFilter, topicFilter, sentimentFilter]);

  const { data: messages, isLoading, isError } = useMessages(filters);
  const { data: topics } = useTopics();

  useEffect(() => {
    const channel = searchParams.get("channel");
    if (channel && channel !== channelFilter) {
      setChannelFilter(channel);
    }
  }, [channelFilter, searchParams]);

  const channels = useMemo(() => {
    if (!messages) return [];
    return [...new Set(messages.map(m => m.channel))];
  }, [messages]);

  return (
    <>
      <Header title={t("feed.title")} />
      <PageTransition>
        <div className="p-6 space-y-4">
          <div className="flex flex-wrap items-center gap-3 bg-card rounded-xl border border-border p-4">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input
                type="text"
                placeholder={t("feed.search")}
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2 bg-muted rounded-lg text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all duration-200"
              />
            </div>

            <select
              value={channelFilter}
              onChange={e => setChannelFilter(e.target.value)}
              className="bg-muted rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all duration-200"
            >
              <option value="All">{t("feed.allChannels")}</option>
              {channels.map(c => <option key={c} value={c}>{c}</option>)}
            </select>

            <select
              value={topicFilter}
              onChange={e => setTopicFilter(e.target.value)}
              className="bg-muted rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all duration-200"
            >
              <option value="All">{t("feed.allTopics")}</option>
              {(topics || []).map(topic => (
                <option key={topic.cluster_id} value={topic.cluster_id}>
                  {topic.label}
                </option>
              ))}
            </select>

            <select
              value={sentimentFilter}
              onChange={e => setSentimentFilter(e.target.value)}
              className="bg-muted rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all duration-200"
            >
              {sentiments.map(s => <option key={s} value={s}>{s}</option>)}
            </select>

            <button
              onClick={() => setLiveMode(!liveMode)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-300 ${
                liveMode
                  ? "bg-positive/10 text-positive border border-positive/20"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              <Radio className={`w-3.5 h-3.5 ${liveMode ? "animate-pulse" : ""}`} />
              {t("feed.live")}
            </button>
          </div>

          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {isLoading ? t("feed.loading") : `${t("feed.showing")} ${(messages || []).length} ${t("feed.messages")}`}
              {!isDemo && (
                <span className="ml-2 text-positive text-xs font-medium">{t("feed.liveApi")}</span>
              )}
            </span>
            <Filter className="w-4 h-4" />
          </div>

          {isError && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-3 p-4 bg-destructive/10 border border-destructive/20 rounded-xl text-sm text-destructive"
            >
              <WifiOff className="w-5 h-5 shrink-0" />
              <div>
                <p className="font-medium">{t("feed.cannotReachApi")}</p>
                <p className="text-xs opacity-75">{t("feed.apiHint")}</p>
              </div>
            </motion.div>
          )}

          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 text-primary animate-spin" />
            </div>
          ) : (
            <div className="space-y-3">
              <AnimatePresence mode="popLayout">
                {(messages || []).map((msg, i) => (
                  <MessageCard key={msg.event_id} message={msg} index={i} />
                ))}
              </AnimatePresence>
              {(messages || []).length === 0 && !isError && (
                <p className="text-center text-muted-foreground py-8">{t("feed.noMessages")}</p>
              )}
            </div>
          )}
        </div>
      </PageTransition>
    </>
  );
}
