"use client";

import { useState, useMemo } from "react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { MessageCard } from "@/components/feed/message-card";
import { useMessages, useTopics } from "@/lib/use-data";
import { useDemoContext } from "@/components/providers";
import { Search, Filter, Radio, Loader2, WifiOff } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

const sentiments = ["All", "Positive", "Neutral", "Negative"];

export default function FeedPage() {
  const { isDemo } = useDemoContext();
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

  const channels = useMemo(() => {
    if (!messages) return [];
    return [...new Set(messages.map(m => m.channel))];
  }, [messages]);

  return (
    <>
      <Header title="Feed" />
      <PageTransition>
        <div className="p-6 space-y-4">
          <div className="flex flex-wrap items-center gap-3 bg-card rounded-xl border border-border p-4">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search messages..."
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
              <option value="All">All Channels</option>
              {channels.map(c => <option key={c} value={c}>{c}</option>)}
            </select>

            <select
              value={topicFilter}
              onChange={e => setTopicFilter(e.target.value)}
              className="bg-muted rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all duration-200"
            >
              <option value="All">All Topics</option>
              {(topics || []).map(t => <option key={t.cluster_id} value={t.label}>{t.label}</option>)}
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
              Live
            </button>
          </div>

          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {isLoading ? "Loading..." : `Showing ${(messages || []).length} messages`}
              {!isDemo && (
                <span className="ml-2 text-positive text-xs font-medium">(Live API)</span>
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
                <p className="font-medium">Cannot reach API</p>
                <p className="text-xs opacity-75">Make sure analytics_duckdb is running on the configured URL, or switch to Demo mode.</p>
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
                <p className="text-center text-muted-foreground py-8">No messages match your filters.</p>
              )}
            </div>
          )}
        </div>
      </PageTransition>
    </>
  );
}
