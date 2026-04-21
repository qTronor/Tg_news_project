"use client";

import { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslation } from "@/lib/i18n";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { useGraph, type GraphMode } from "@/lib/use-data";
import { Search, Loader2 } from "lucide-react";
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

function GraphContent() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const focusParam = searchParams.get("focus") || undefined;
  const clusterIdParam = searchParams.get("clusterId") || undefined;
  const initialMode = searchParams.get("mode") === "propagation" ? "propagation" : "overview";
  const [search, setSearch] = useState("");
  const [depth, setDepth] = useState(2);
  const [mode, setMode] = useState<GraphMode>(initialMode);
  const [showTopics, setShowTopics] = useState(true);
  const [showChannels, setShowChannels] = useState(true);
  const [showEntities, setShowEntities] = useState(true);
  const [showMessages, setShowMessages] = useState(true);

  const { data: graphData, isLoading } = useGraph(focusParam, depth, mode, clusterIdParam);

  const filteredData = graphData ? {
    nodes: graphData.nodes.filter(n => {
      if (!showTopics && n.type === "topic") return false;
      if (!showChannels && n.type === "channel") return false;
      if (!showEntities && n.type.startsWith("entity_")) return false;
      if (!showMessages && n.type === "message") return false;
      if (search && !n.label.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    }),
    edges: graphData.edges,
  } : { nodes: [], edges: [] };

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
              onClick={() => setMode(value)}
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

        <div className="flex items-center gap-2 text-sm">
          <span className="text-[#aeb5cf]">{t("graph.depth")}:</span>
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

        <div className="flex items-center gap-3 text-sm">
          {[
            { key: "topics", label: t("graph.topics"), value: showTopics, set: setShowTopics },
            { key: "channels", label: t("graph.channels"), value: showChannels, set: setShowChannels },
            { key: "entities", label: t("graph.entities"), value: showEntities, set: setShowEntities },
            { key: "messages", label: "Messages", value: showMessages, set: setShowMessages },
          ].map(f => (
            <label key={f.key} className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={f.value}
                onChange={e => f.set(e.target.checked)}
                className="rounded border-white/20 bg-[#23243a] text-[#6f78ff] focus:ring-[#6f78ff]/30"
              />
              <span className="text-[#aeb5cf]">{f.label}</span>
            </label>
          ))}
        </div>
      </div>

      {mode === "propagation" && (
        <div className="text-xs text-[#aeb5cf]">
          {clusterIdParam ? `Cluster focus: ${clusterIdParam}` : "Propagation mode requires a cluster focus."}
        </div>
      )}

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
