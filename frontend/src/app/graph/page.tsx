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
    <div className="w-full h-full flex items-center justify-center text-muted-foreground">
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
    <div className="p-6 h-[calc(100vh-4rem)] flex flex-col gap-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input
            type="text"
            placeholder={t("graph.searchNode")}
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 bg-card border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all"
          />
        </div>

        <div className="flex items-center gap-2 text-sm">
          {(["overview", "propagation"] as GraphMode[]).map(value => (
            <button
              key={value}
              onClick={() => setMode(value)}
              className={`rounded-lg px-3 py-2 text-xs font-medium transition-all ${
                mode === value
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              {value === "overview" ? "Overview" : "Propagation"}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">{t("graph.depth")}:</span>
          {[1, 2, 3].map(d => (
            <button
              key={d}
              onClick={() => setDepth(d)}
              className={`w-8 h-8 rounded-lg text-xs font-medium transition-all ${
                depth === d ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground"
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
                className="rounded border-border text-primary focus:ring-primary/30"
              />
              <span className="text-muted-foreground">{f.label}</span>
            </label>
          ))}
        </div>
      </div>

      {mode === "propagation" && (
        <div className="text-xs text-muted-foreground">
          {clusterIdParam ? `Cluster focus: ${clusterIdParam}` : "Propagation mode requires a cluster focus."}
        </div>
      )}

      <div className="flex-1 bg-card rounded-xl border border-border overflow-hidden">
        {isLoading ? (
          <div className="w-full h-full flex items-center justify-center">
            <Loader2 className="w-6 h-6 text-primary animate-spin" />
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
