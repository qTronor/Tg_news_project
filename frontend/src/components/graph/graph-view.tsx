"use client";

import { useRef, useEffect, useCallback, useState } from "react";
import cytoscape, { type Core, type EventObject } from "cytoscape";
import type { GraphData, GraphNode } from "@/types";
import { motion, AnimatePresence } from "framer-motion";
import { Maximize2, Minus, Plus, RotateCcw, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { SourceStatusBadge } from "@/components/topics/source-status-badge";
import type { SourceStatus } from "@/types";

interface Props {
  data: GraphData;
  focusNodeId?: string;
  onNodeClick?: (node: GraphNode) => void;
}

function nodeColor(type: string): string {
  switch (type) {
    case "topic": return "#a8e6a1";
    case "channel": return "#55d6b2";
    case "message": return "#c5d845";
    case "entity_per": return "#2f3cff";
    case "entity_org": return "#98a1bd";
    case "entity_loc": return "#ff2c25";
    default: return "#8f98b3";
  }
}

function sourceStatusColor(status?: SourceStatus): string | null {
  switch (status) {
    case "exact":
      return "#a8e6a1";
    case "probable":
      return "#c5d845";
    case "unknown":
      return "#8f98b3";
    default:
      return null;
  }
}

function nodeSize(weight?: number): number {
  const safeWeight = Number.isFinite(weight) && weight ? weight : 1;
  return Math.max(11, Math.min(34, 9 + Math.sqrt(safeWeight) * 2.8));
}

function sameCommunity(edge: cytoscape.EdgeSingular): boolean {
  const sourceCommunity = edge.source().data("community");
  const targetCommunity = edge.target().data("community");
  return sourceCommunity !== undefined && sourceCommunity !== null && sourceCommunity === targetCommunity;
}

const obsidianLayout: cytoscape.CoseLayoutOptions = {
  name: "cose",
  animate: true,
  animationDuration: 1400,
  animationEasing: "ease-out",
  refresh: 24,
  fit: true,
  padding: 70,
  randomize: true,
  nodeDimensionsIncludeLabels: false,
  componentSpacing: 150,
  nodeOverlap: 36,
  nodeRepulsion: (node: cytoscape.NodeSingular) => {
    const weight = node.data("weight") || 1;
    const type = node.data("nodeType");
    const typeBoost = type === "topic" ? 1.35 : type === "channel" ? 1.18 : 1;
    return Math.min(52000, (24000 + Math.sqrt(weight) * 2800) * typeBoost);
  },
  idealEdgeLength: (edge: cytoscape.EdgeSingular) => {
    const weight = edge.data("weight") || 1;
    const communityFactor = sameCommunity(edge) ? 0.72 : 1.18;
    return Math.max(62, (152 - Math.sqrt(weight) * 7) * communityFactor);
  },
  edgeElasticity: (edge: cytoscape.EdgeSingular) => {
    const weight = edge.data("weight") || 1;
    const communityBoost = sameCommunity(edge) ? 1.22 : 0.82;
    return Math.max(48, Math.min(150, (70 + Math.sqrt(weight) * 9) * communityBoost));
  },
  nestingFactor: 0.08,
  gravity: 0.16,
  numIter: 2300,
  initialTemp: 280,
  coolingFactor: 0.968,
  minTemp: 0.6,
};

const settleLayout: cytoscape.CoseLayoutOptions = {
  ...obsidianLayout,
  randomize: false,
  fit: false,
  animationDuration: 520,
  numIter: 420,
  initialTemp: 72,
  minTemp: 1,
};

export function GraphView({ data, focusNodeId, onNodeClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const dragPullRef = useRef<Map<string, { position: cytoscape.Position; strength: number }>>(new Map());
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const zoomBy = useCallback((factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    const zoom = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() * factor));
    cy.animate(
      {
        zoom,
        center: { eles: cy.elements(":visible") },
      },
      { duration: 180, easing: "ease-out" }
    );
  }, []);

  const fitGraph = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.animate(
      {
        fit: { eles: cy.elements(":visible"), padding: 72 },
      },
      { duration: 260, easing: "ease-out" }
    );
  }, []);

  const relaxGraph = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.layout({ ...settleLayout, fit: true, animationDuration: 680 }).run();
  }, []);

  const clearSelection = useCallback(() => {
    const cy = cyRef.current;
    cy?.elements().removeClass("highlighted faded hovered");
    cy?.nodes().unselect();
    setSelectedNode(null);
  }, []);

  const initGraph = useCallback(() => {
    if (!containerRef.current) return;
    if (cyRef.current) cyRef.current.destroy();

    const elements = [
      ...data.nodes.map(n => ({
        data: {
          id: n.id,
          label: n.label,
          nodeType: n.type,
          weight: n.weight,
          community: n.community,
          channel: n.channel,
          messageId: n.message_id,
          messageDate: n.message_date,
          sourceStatus: n.source_status,
        },
      })),
      ...data.edges
        .filter(e =>
          data.nodes.some(n => n.id === e.source) &&
          data.nodes.some(n => n.id === e.target)
        )
        .map((e, i) => ({
          data: {
            id: `edge-${i}`,
            source: e.source,
            target: e.target,
            weight: e.weight,
            edgeType: e.type,
          },
        })),
    ];

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: "node",
          style: {
            label: "",
            "font-size": "11px",
            "font-weight": 500,
            color: "#e7eaff",
            "text-outline-color": "#1b1c2d",
            "text-outline-width": 3,
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 7,
            "background-color": (ele: cytoscape.NodeSingular) => nodeColor(ele.data("nodeType")),
            shape: "ellipse",
            width: (ele: cytoscape.NodeSingular) => nodeSize(ele.data("weight")),
            height: (ele: cytoscape.NodeSingular) => nodeSize(ele.data("weight")),
            "border-width": 0.75,
            "border-color": (ele: cytoscape.NodeSingular) =>
              sourceStatusColor(ele.data("sourceStatus")) || nodeColor(ele.data("nodeType")),
            "border-opacity": 0.45,
            "background-opacity": 0.95,
            "overlay-opacity": 0,
            "transition-property": "background-color, border-color, background-opacity, line-opacity, width, height, border-width",
            "transition-duration": 220,
          },
        },
        {
          selector: "node.hovered, node:selected",
          style: {
            label: "data(label)",
            "z-index": 20,
            "border-width": 2.5,
            "border-color": "#f5f7ff",
            "background-opacity": 1,
          },
        },
        {
          selector: "node:selected",
          style: {
            width: (ele: cytoscape.NodeSingular) => nodeSize(ele.data("weight")) + 6,
            height: (ele: cytoscape.NodeSingular) => nodeSize(ele.data("weight")) + 6,
          },
        },
        {
          selector: "edge",
          style: {
            width: (ele: cytoscape.EdgeSingular) => Math.max(0.55, Math.min(2.2, Math.sqrt(ele.data("weight") || 1) / 7)),
            "line-color": "#8b91aa",
            "line-opacity": 0.32,
            "curve-style": "straight",
            "target-arrow-shape": "none",
            "target-arrow-color": (ele: cytoscape.EdgeSingular) =>
              ele.data("edgeType")?.includes("propagates") ? "#c5d845" : "#8b91aa",
            "arrow-scale": 0,
            "overlay-opacity": 0,
            "transition-property": "line-color, line-opacity, width",
            "transition-duration": 180,
          },
        },
        {
          selector: "node.highlighted",
          style: {
            "background-opacity": 1,
            "border-width": 2.25,
            "border-color": "#f5f7ff",
          },
        },
        {
          selector: "node.faded",
          style: {
            "background-opacity": 0.18,
            "border-opacity": 0.08,
            "text-opacity": 0.18,
          },
        },
        {
          selector: "edge.faded",
          style: {
            "line-opacity": 0.045,
          },
        },
        {
          selector: "edge.highlighted",
          style: {
            "line-opacity": 0.75,
            "line-color": "#c2c7dd",
            width: (ele: cytoscape.EdgeSingular) => Math.max(1.1, Math.min(2.8, Math.sqrt(ele.data("weight") || 1) / 5)),
          },
        },
      ],
      layout: obsidianLayout,
      minZoom: 0.3,
      maxZoom: 4,
      wheelSensitivity: 0.18,
    });

    cy.ready(() => {
      setTimeout(() => {
        cy.layout({ ...settleLayout, fit: true, animationDuration: 720 }).run();
      }, 150);
    });

    cy.on("mouseover", "node", (evt: EventObject) => {
      evt.target.addClass("hovered");
    });

    cy.on("mouseout", "node", (evt: EventObject) => {
      if (!evt.target.selected()) {
        evt.target.removeClass("hovered");
      }
    });

    cy.on("grab", "node", (evt: EventObject) => {
      const grabbed = evt.target;
      const pullMap = new Map<string, { position: cytoscape.Position; strength: number }>();
      pullMap.set(grabbed.id(), { position: { ...grabbed.position() }, strength: 1 });

      grabbed.connectedEdges().forEach((edge: cytoscape.EdgeSingular) => {
        const neighbor = edge.connectedNodes().not(grabbed)[0];
        if (!neighbor?.length) return;

        const weight = edge.data("weight") || 1;
        const strength = Math.max(0.46, Math.min(0.72, 0.42 + Math.sqrt(weight) / 18));
        pullMap.set(neighbor.id(), { position: { ...neighbor.position() }, strength });

        neighbor.connectedEdges().forEach((secondEdge: cytoscape.EdgeSingular) => {
          const secondNeighbor = secondEdge.connectedNodes().not(neighbor)[0];
          if (!secondNeighbor?.length || secondNeighbor.same(grabbed) || pullMap.has(secondNeighbor.id())) return;

          const secondWeight = secondEdge.data("weight") || 1;
          const secondStrength = Math.max(0.16, Math.min(0.34, 0.14 + Math.sqrt(secondWeight) / 28));
          pullMap.set(secondNeighbor.id(), { position: { ...secondNeighbor.position() }, strength: secondStrength });
        });
      });

      dragPullRef.current = pullMap;
    });

    cy.on("drag", "node", (evt: EventObject) => {
      const dragged = evt.target;
      const origin = dragPullRef.current.get(dragged.id());
      if (!origin) return;

      const current = dragged.position();
      const delta = {
        x: current.x - origin.position.x,
        y: current.y - origin.position.y,
      };

      dragPullRef.current.forEach((entry, nodeId) => {
        if (nodeId === dragged.id()) return;

        const pulledNode = cy.getElementById(nodeId);
        if (!pulledNode.length) return;

        pulledNode.position({
          x: entry.position.x + delta.x * entry.strength,
          y: entry.position.y + delta.y * entry.strength,
        });
      });
    });

    cy.on("dragfree", "node", () => {
      dragPullRef.current.clear();
      cy.layout(settleLayout).run();
    });

    cy.on("tap", "node", (evt: EventObject) => {
      const node = evt.target;
      const nodeData: GraphNode = {
        id: node.data("id"),
        label: node.data("label"),
        type: node.data("nodeType"),
        weight: node.data("weight"),
        community: node.data("community"),
        channel: node.data("channel"),
        message_id: node.data("messageId"),
        message_date: node.data("messageDate"),
        source_status: node.data("sourceStatus"),
      };
      setSelectedNode(nodeData);
      onNodeClick?.(nodeData);

      cy.elements().removeClass("highlighted faded");
      const neighborhood = node.neighborhood().add(node);
      neighborhood.addClass("highlighted");
      node.connectedEdges().addClass("highlighted");
      cy.elements().not(neighborhood).addClass("faded");
    });

    cy.on("tap", (evt: EventObject) => {
      if (evt.target === cy) {
        clearSelection();
      }
    });

    cyRef.current = cy;

    if (focusNodeId) {
      const focusNode = cy.getElementById(focusNodeId);
      if (focusNode.length) {
        setTimeout(() => {
          cy.animate({
            center: { eles: focusNode },
            zoom: 1.5,
          });
          focusNode.select();
          const neighborhood = focusNode.neighborhood().add(focusNode);
          neighborhood.addClass("highlighted");
          focusNode.connectedEdges().addClass("highlighted");
          cy.elements().not(neighborhood).addClass("faded");
          setSelectedNode({
            id: focusNode.data("id"),
            label: focusNode.data("label"),
            type: focusNode.data("nodeType"),
            weight: focusNode.data("weight"),
            community: focusNode.data("community"),
            channel: focusNode.data("channel"),
            message_id: focusNode.data("messageId"),
            message_date: focusNode.data("messageDate"),
            source_status: focusNode.data("sourceStatus"),
          });
        }, 1000);
      }
    }
  }, [clearSelection, data, focusNodeId, onNodeClick]);

  useEffect(() => {
    initGraph();
    return () => { cyRef.current?.destroy(); };
  }, [initGraph]);

  return (
    <div className="relative w-full h-full overflow-hidden bg-[#1b1c2d]">
      <div ref={containerRef} className="h-full w-full cursor-grab active:cursor-grabbing" />

      <div className="absolute right-4 bottom-4 z-10 flex flex-col overflow-hidden rounded-lg border border-white/10 bg-[#23243a]/90 shadow-xl shadow-black/25 backdrop-blur-md">
        <button
          type="button"
          onClick={() => zoomBy(1.2)}
          className="flex h-10 w-10 items-center justify-center border-b border-white/10 text-[#d9ddef] transition-colors hover:bg-white/10 hover:text-white"
          aria-label="Zoom in"
          title="Zoom in"
        >
          <Plus className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => zoomBy(1 / 1.2)}
          className="flex h-10 w-10 items-center justify-center border-b border-white/10 text-[#d9ddef] transition-colors hover:bg-white/10 hover:text-white"
          aria-label="Zoom out"
          title="Zoom out"
        >
          <Minus className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={fitGraph}
          className="flex h-10 w-10 items-center justify-center border-b border-white/10 text-[#d9ddef] transition-colors hover:bg-white/10 hover:text-white"
          aria-label="Fit graph"
          title="Fit graph"
        >
          <Maximize2 className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={relaxGraph}
          className="flex h-10 w-10 items-center justify-center text-[#d9ddef] transition-colors hover:bg-white/10 hover:text-white"
          aria-label="Relax layout"
          title="Relax layout"
        >
          <RotateCcw className="h-4 w-4" />
        </button>
      </div>

      <div className="pointer-events-none absolute left-4 top-4 flex max-w-[calc(100%-2rem)] flex-wrap gap-2 opacity-90">
        {[
          { label: "Topic", color: nodeColor("topic") },
          { label: "Channel", color: nodeColor("channel") },
          { label: "Message", color: nodeColor("message") },
          { label: "PER", color: nodeColor("entity_per") },
          { label: "ORG", color: nodeColor("entity_org") },
          { label: "LOC", color: nodeColor("entity_loc") },
        ].map(item => (
          <div key={item.label} className="flex items-center gap-1.5 rounded-full border border-white/10 bg-[#23243a]/75 px-2.5 py-1 text-xs text-[#d9ddef] backdrop-blur-sm">
            <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
            {item.label}
          </div>
        ))}
      </div>

      <AnimatePresence>
        {selectedNode && (
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={{ duration: 0.2 }}
            className="absolute right-4 top-4 w-72 rounded-lg border border-white/10 bg-[#23243a]/95 p-4 text-[#eef1ff] shadow-2xl shadow-black/30 backdrop-blur-md"
          >
            <div className="flex items-start justify-between">
              <div>
                <Badge variant="entity" color={nodeColor(selectedNode.type)}>
                  {selectedNode.type}
                </Badge>
                {selectedNode.source_status && (
                  <div className="mt-2">
                    <SourceStatusBadge status={selectedNode.source_status} />
                  </div>
                )}
                <h3 className="mt-2 text-sm font-semibold text-[#f5f7ff]">{selectedNode.label}</h3>
              </div>
              <button onClick={clearSelection} className="text-[#9aa2bf] transition-colors hover:text-[#f5f7ff]">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="mt-3 space-y-1.5 text-xs text-[#aeb5cf]">
              <div className="flex justify-between">
                <span>Weight</span>
                <span className="font-medium text-[#f5f7ff]">{selectedNode.weight}</span>
              </div>
              {selectedNode.community !== undefined && (
                <div className="flex justify-between">
                  <span>Community</span>
                  <span className="font-medium text-[#f5f7ff]">#{selectedNode.community}</span>
                </div>
              )}
              {"channel" in selectedNode && selectedNode.channel && (
                <div className="flex justify-between">
                  <span>Channel</span>
                  <span className="font-medium text-[#f5f7ff]">{selectedNode.channel}</span>
                </div>
              )}
              {"message_id" in selectedNode && selectedNode.message_id !== undefined && (
                <div className="flex justify-between">
                  <span>Message</span>
                  <span className="font-medium text-[#f5f7ff]">#{selectedNode.message_id}</span>
                </div>
              )}
              {"source_status" in selectedNode && selectedNode.source_status && (
                <div className="flex justify-between">
                  <span>Source</span>
                  <span className="font-medium capitalize text-[#f5f7ff]">{selectedNode.source_status}</span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
