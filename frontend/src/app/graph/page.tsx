"use client";

import { useMemo, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "@/lib/i18n";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { useGlobalTimeRange } from "@/components/providers";
import { useGraph, type GraphMode } from "@/lib/use-data";
import { CalendarDays, Check, ChevronDown, Filter, Loader2, Search, X } from "lucide-react";
import dynamic from "next/dynamic";

function GraphViewLoading() {
  const { t } = useTranslation();
  return (
    <div className="flex h-full w-full items-center justify-center bg-[#1b1c2d] text-[#aeb5cf]">
      {t("graph.loadingGraph")}
    </div>
  );
}

const GraphView = dynamic(
  () => import("@/components/graph/graph-view").then(m => ({ default: m.GraphView })),
  { ssr: false, loading: () => <GraphViewLoading /> }
);

type SourceFilter = "all" | "exact" | "probable" | "unknown";

function toDateTimeLocal(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset();
  const local = new Date(date.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

function fromDateTimeLocal(value: string): string {
  return new Date(value).toISOString();
}

function GraphContent() {
  const { t } = useTranslation();
  const { range, setRange } = useGlobalTimeRange();
  const router = useRouter();
  const searchParams = useSearchParams();
  const focusParam = searchParams.get("focus") || undefined;
  const clusterIdParam = searchParams.get("clusterId") || undefined;
  const mode: GraphMode = searchParams.get("mode") === "propagation" ? "propagation" : "overview";
  const [search, setSearch] = useState("");
  const [depth, setDepth] = useState(2);
  const [showTopics, setShowTopics] = useState(true);
  const [selectedTopicId, setSelectedTopicId] = useState("all");
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [channelsMenuOpen, setChannelsMenuOpen] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [entityTypes, setEntityTypes] = useState({
    entity_per: true,
    entity_org: true,
    entity_loc: true,
  });
  const [showMessages, setShowMessages] = useState(true);

  const selectedClusterId = selectedTopicId.startsWith("topic-")
    ? selectedTopicId.slice("topic-".length)
    : undefined;
  const graphClusterId = clusterIdParam || selectedClusterId;
  const { data: graphData, isLoading } = useGraph(focusParam, depth, mode, graphClusterId);

  const topicNodes = useMemo(
    () => (graphData?.nodes || []).filter((node) => node.type === "topic"),
    [graphData],
  );

  const channelNodes = useMemo(
    () => (graphData?.nodes || [])
      .filter((node) => node.type === "channel")
      .sort((a, b) => b.weight - a.weight || a.label.localeCompare(b.label)),
    [graphData],
  );

  const topicReachableIds = useMemo(() => {
    if (!graphData || selectedTopicId === "all") return null;
    const seen = new Set<string>([selectedTopicId]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const edge of graphData.edges) {
        if (seen.has(edge.source) && !seen.has(edge.target)) {
          seen.add(edge.target);
          changed = true;
        }
        if (seen.has(edge.target) && !seen.has(edge.source)) {
          seen.add(edge.source);
          changed = true;
        }
      }
    }
    return seen;
  }, [graphData, selectedTopicId]);

  const filteredData = useMemo(() => {
    if (!graphData) return { nodes: [], edges: [] };
    const channelSet = new Set(selectedChannels);
    const searchText = search.trim().toLowerCase();

    const nodes = graphData.nodes.filter(n => {
      if (topicReachableIds && !topicReachableIds.has(n.id)) return false;
      if (!showTopics && n.type === "topic") return false;
      if (!showMessages && n.type === "message") return false;
      if (n.type.startsWith("entity_") && !entityTypes[n.type as keyof typeof entityTypes]) return false;
      if (channelSet.size > 0) {
        if (n.type === "channel" && !channelSet.has(n.label)) return false;
        if (n.type === "message" && (!n.channel || !channelSet.has(n.channel))) return false;
      }
      if (
        sourceFilter !== "all" &&
        (n.type === "topic" || n.type === "message") &&
        (n.source_status || "unknown") !== sourceFilter
      ) return false;
      if (searchText && !`${n.label} ${n.channel || ""}`.toLowerCase().includes(searchText)) return false;
      return true;
    });
    const ids = new Set(nodes.map((node) => node.id));
    return {
      nodes,
      edges: graphData.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
    };
  }, [entityTypes, graphData, search, selectedChannels, showMessages, showTopics, sourceFilter, topicReachableIds]);

  const toggleChannel = (channel: string) => {
    setSelectedChannels((current) =>
      current.includes(channel)
        ? current.filter((item) => item !== channel)
        : [...current, channel]
    );
  };

  const setCustomDate = (side: "from" | "to", value: string) => {
    if (!value) return;
    setRange("custom", side === "from" ? fromDateTimeLocal(value) : range.from, side === "to" ? fromDateTimeLocal(value) : range.to);
  };

  const modeHint = mode === "overview"
    ? "Overview показывает обзорную карту: темы, каналы, сущности и пример сообщений."
    : "Propagation показывает путь распространения внутри выбранной темы: сообщение-источник и последующие публикации.";

  const setModeQuery = (nextMode: GraphMode) => {
    const params = new URLSearchParams(searchParams.toString());
    if (nextMode === "overview") {
      params.delete("mode");
    } else {
      params.set("mode", nextMode);
    }
    router.push(`/graph?${params.toString()}`);
  };

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col gap-4 bg-[#171827] p-4 md:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8f98b3]" />
          <input
            type="text"
            placeholder={t("graph.searchNode")}
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full rounded-lg border border-white/10 bg-[#23243a] py-2 pl-9 pr-4 text-sm text-[#eef1ff] outline-none transition-all placeholder:text-[#8f98b3] focus:border-[#6f78ff] focus:ring-2 focus:ring-[#6f78ff]/25"
          />
        </div>

        <div className="flex items-center gap-2 text-sm">
          {(["overview", "propagation"] as GraphMode[]).map(value => (
            <button
              key={value}
              onClick={() => setModeQuery(value)}
              className={`rounded-lg px-3 py-2 text-xs font-medium transition-all ${
                mode === value
                  ? "bg-[#6f78ff] text-white"
                  : "bg-[#23243a] text-[#aeb5cf] hover:text-[#eef1ff]"
              }`}
            >
              {value === "overview" ? "Overview" : "Propagation"}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 text-sm" title="Depth controls how many related channels, entities and messages are expanded per topic.">
          <span className="text-[#aeb5cf]">{t("graph.depth")}</span>
          {[1, 2, 3].map(d => (
            <button
              key={d}
              onClick={() => setDepth(d)}
              className={`w-8 h-8 rounded-lg text-xs font-medium transition-all ${
                depth === d ? "bg-[#6f78ff] text-white" : "bg-[#23243a] text-[#aeb5cf] hover:text-[#eef1ff]"
              }`}
            >
              {d}
            </button>
          ))}
        </div>

        <select
          value={selectedTopicId}
          onChange={(event) => setSelectedTopicId(event.target.value)}
          className="max-w-72 rounded-lg border border-white/10 bg-[#23243a] px-3 py-2 text-xs text-[#eef1ff] outline-none focus:border-[#6f78ff]"
        >
          <option value="all">All topics</option>
          {topicNodes.map((node) => (
            <option key={node.id} value={node.id}>{node.label}</option>
          ))}
        </select>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-white/10 bg-[#202137] px-3 py-2">
        <div className="flex items-center gap-2 text-xs text-[#aeb5cf]">
          <Filter className="h-3.5 w-3.5" />
          <span>{filteredData.nodes.length} nodes</span>
          <span>{filteredData.edges.length} links</span>
        </div>

        <div className="flex items-center gap-1 text-xs">
          {[
            { key: "topics", label: t("graph.topics"), value: showTopics, set: setShowTopics },
            { key: "messages", label: "Messages", value: showMessages, set: setShowMessages },
          ].map(f => (
            <button
              key={f.key}
              type="button"
              onClick={() => f.set(!f.value)}
              className={`rounded-md px-2.5 py-1.5 font-medium transition-colors ${
                f.value ? "bg-[#6f78ff] text-white" : "bg-[#171827] text-[#aeb5cf] hover:text-white"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1 text-xs">
          {[
            { key: "entity_per", label: "People" },
            { key: "entity_org", label: "Orgs" },
            { key: "entity_loc", label: "Places" },
          ].map(item => (
            <button
              key={item.key}
              type="button"
              onClick={() => setEntityTypes((current) => ({ ...current, [item.key]: !current[item.key as keyof typeof current] }))}
              className={`rounded-md px-2.5 py-1.5 font-medium transition-colors ${
                entityTypes[item.key as keyof typeof entityTypes]
                  ? "bg-[#30314b] text-[#eef1ff]"
                  : "bg-[#171827] text-[#717b9b] hover:text-white"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <select
          value={sourceFilter}
          onChange={(event) => setSourceFilter(event.target.value as SourceFilter)}
          className="rounded-lg border border-white/10 bg-[#171827] px-2.5 py-1.5 text-xs text-[#eef1ff] outline-none"
        >
          <option value="all">All source states</option>
          <option value="exact">Exact source</option>
          <option value="probable">Probable source</option>
          <option value="unknown">Unknown source</option>
        </select>

        <div className="flex items-center gap-2 text-xs text-[#aeb5cf]">
          <CalendarDays className="h-3.5 w-3.5" />
          <input
            type="datetime-local"
            value={toDateTimeLocal(range.from)}
            onChange={(event) => setCustomDate("from", event.target.value)}
            className="w-36 rounded-md border border-white/10 bg-[#171827] px-2 py-1 text-[#eef1ff] outline-none"
          />
          <input
            type="datetime-local"
            value={toDateTimeLocal(range.to)}
            onChange={(event) => setCustomDate("to", event.target.value)}
            className="w-36 rounded-md border border-white/10 bg-[#171827] px-2 py-1 text-[#eef1ff] outline-none"
          />
        </div>

        <div className="relative">
          <button
            type="button"
            onClick={() => setChannelsMenuOpen((open) => !open)}
            className="flex min-w-[220px] items-center justify-between gap-3 rounded-lg border border-white/10 bg-[#171827] px-3 py-1.5 text-xs text-[#eef1ff] outline-none transition-colors hover:border-white/20"
          >
            <span className="truncate text-left">
              {selectedChannels.length === 0
                ? "All channels"
                : selectedChannels.length === 1
                  ? selectedChannels[0]
                  : `${selectedChannels.length} channels selected`}
            </span>
            <ChevronDown className={`h-3.5 w-3.5 shrink-0 text-[#8f98b3] transition-transform ${channelsMenuOpen ? "rotate-180" : ""}`} />
          </button>

          {channelsMenuOpen && (
            <div className="absolute left-0 top-full z-20 mt-2 w-[300px] rounded-lg border border-white/10 bg-[#171827] p-2 shadow-2xl shadow-black/30">
              <div className="flex items-center justify-between gap-2 border-b border-white/10 px-2 pb-2 text-[11px] text-[#8f98b3]">
                <span>Filter channels</span>
                {selectedChannels.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setSelectedChannels([])}
                    className="text-[#eef1ff] transition-colors hover:text-white"
                  >
                    Clear
                  </button>
                )}
              </div>
              <div className="mt-2 max-h-64 overflow-y-auto">
                {channelNodes.map((node) => {
                  const active = selectedChannels.includes(node.label);
                  return (
                    <label
                      key={node.id}
                      className="flex cursor-pointer items-center justify-between gap-3 rounded-md px-2 py-2 text-xs text-[#eef1ff] transition-colors hover:bg-white/5"
                    >
                      <span className="truncate">{node.label}</span>
                      <span
                        className={`flex h-4 w-4 items-center justify-center rounded border ${
                          active ? "border-[#55d6b2] bg-[#55d6b2] text-[#10221d]" : "border-white/15 text-transparent"
                        }`}
                      >
                        <Check className="h-3 w-3" />
                      </span>
                      <input
                        type="checkbox"
                        checked={active}
                        onChange={() => toggleChannel(node.label)}
                        className="sr-only"
                      />
                    </label>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {selectedChannels.length > 0 && (
          <div className="flex max-w-full flex-wrap gap-1">
            {selectedChannels.map((channel) => (
              <button
                key={channel}
                type="button"
                onClick={() => toggleChannel(channel)}
                className="inline-flex items-center gap-1 rounded-md bg-[#55d6b2] px-2 py-1 text-xs font-medium text-[#10221d]"
              >
                <span className="truncate">{channel}</span>
                <X className="h-3 w-3" />
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="text-xs text-[#aeb5cf]">
        {modeHint}
        {mode === "propagation" && !graphClusterId ? " Select a topic or open a message from feed to build it." : ""}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-white/10 bg-[#1b1c2d]">
        {isLoading ? (
          <div className="w-full h-full flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-[#6f78ff]" />
          </div>
        ) : (
          <GraphView data={filteredData} focusNodeId={focusParam} />
        )}
      </div>
    </div>
  );
}

export default function GraphPage() {
  const { t } = useTranslation();
  return (
    <>
      <Header title={t("graph.title")} />
      <PageTransition>
        <Suspense fallback={<div className="p-6 text-muted-foreground">{t("graph.loading")}</div>}>
          <GraphContent />
        </Suspense>
      </PageTransition>
    </>
  );
}
