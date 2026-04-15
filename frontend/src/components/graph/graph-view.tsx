"use client";

import { useRef, useEffect, useCallback, useState } from "react";
import cytoscape, { type Core, type EventObject } from "cytoscape";
import type { GraphData, GraphNode } from "@/types";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { entityTypeColor } from "@/lib/utils";
import { SourceStatusBadge } from "@/components/topics/source-status-badge";
import type { SourceStatus } from "@/types";

interface Props {
  data: GraphData;
  focusNodeId?: string;
  onNodeClick?: (node: GraphNode) => void;
}

function nodeColor(type: string): string {
  switch (type) {
    case "topic": return "#3b82f6";
    case "channel": return "#22c55e";
    case "message": return "#f59e0b";
    case "entity_per": return "#f97316";
    case "entity_org": return "#8b5cf6";
    case "entity_loc": return "#ef4444";
    default: return "#6b7280";
  }
}

function nodeShape(type: string): string {
  switch (type) {
    case "topic": return "round-diamond";
    case "channel": return "round-hexagon";
    case "message": return "round-rectangle";
    default: return "ellipse";
  }
}

function sourceStatusColor(status?: SourceStatus): string | null {
  switch (status) {
    case "exact":
      return "#15803d";
    case "probable":
      return "#d97706";
    case "unknown":
      return "#64748b";
    default:
      return null;
  }
}

export function GraphView({ data, focusNodeId, onNodeClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

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
            label: "data(label)",
            "font-size": "10px",
            color: "#cbd5e1",
            "text-valign": "bottom",
            "text-margin-y": 6,
            "background-color": (ele: cytoscape.NodeSingular) => nodeColor(ele.data("nodeType")),
            shape: (ele: cytoscape.NodeSingular) => nodeShape(ele.data("nodeType")) as any,
            width: (ele: cytoscape.NodeSingular) => Math.max(20, Math.min(60, Math.sqrt(ele.data("weight")) * 2)),
            height: (ele: cytoscape.NodeSingular) => Math.max(20, Math.min(60, Math.sqrt(ele.data("weight")) * 2)),
            "border-width": 2,
            "border-color": (ele: cytoscape.NodeSingular) =>
              sourceStatusColor(ele.data("sourceStatus")) || nodeColor(ele.data("nodeType")),
            "border-opacity": 0.3,
            "background-opacity": 0.85,
            "overlay-opacity": 0,
            "transition-property": "background-color, border-color, width, height",
            "transition-duration": 300,
          } as any,
        },
        {
          selector: "node:selected",
          style: {
            "border-width": 3,
            "border-color": "#ffffff",
            "background-opacity": 1,
          },
        },
        {
          selector: "edge",
          style: {
            width: (ele: cytoscape.EdgeSingular) => Math.max(1, Math.min(6, ele.data("weight") / 30)),
            "line-color": "#475569",
            "line-opacity": 0.4,
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "target-arrow-color": (ele: cytoscape.EdgeSingular) =>
              ele.data("edgeType")?.includes("propagates") ? "#f59e0b" : "#475569",
            "arrow-scale": 0.6,
            "overlay-opacity": 0,
            "transition-property": "line-color, line-opacity, width",
            "transition-duration": 300,
          } as any,
        },
        {
          selector: "node.highlighted",
          style: {
            "background-opacity": 1,
            "border-width": 3,
            "border-color": "#ffffff",
          },
        },
        {
          selector: "node.faded",
          style: {
            "background-opacity": 0.15,
            "text-opacity": 0.3,
          },
        },
        {
          selector: "edge.faded",
          style: {
            "line-opacity": 0.08,
          },
        },
      ],
      layout: {
        name: "cose",
        animate: true,
        animationDuration: 800,
        nodeRepulsion: () => 8000,
        idealEdgeLength: () => 120,
        gravity: 0.3,
        randomize: false,
      } as any,
      minZoom: 0.3,
      maxZoom: 3,
      wheelSensitivity: 0.3,
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
      cy.elements().not(neighborhood).addClass("faded");
    });

    cy.on("tap", (evt: EventObject) => {
      if (evt.target === cy) {
        cy.elements().removeClass("highlighted faded");
        setSelectedNode(null);
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
          } as any);
          focusNode.select();
          const neighborhood = focusNode.neighborhood().add(focusNode);
          neighborhood.addClass("highlighted");
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
  }, [data, focusNodeId, onNodeClick]);

  useEffect(() => {
    initGraph();
    return () => { cyRef.current?.destroy(); };
  }, [initGraph]);

  return (
    <div className="relative w-full h-full">
      <div ref={containerRef} className="w-full h-full" />

      <div className="absolute top-4 left-4 flex flex-wrap gap-2">
        {[
          { label: "Topic", color: "#3b82f6" },
          { label: "Channel", color: "#22c55e" },
          { label: "Message", color: "#f59e0b" },
          { label: "PER", color: "#f97316" },
          { label: "ORG", color: "#8b5cf6" },
          { label: "LOC", color: "#ef4444" },
          { label: "Exact", color: "#15803d" },
          { label: "Probable", color: "#d97706" },
          { label: "Unknown", color: "#64748b" },
        ].map(item => (
          <div key={item.label} className="flex items-center gap-1.5 bg-card/80 backdrop-blur-sm rounded-full px-2.5 py-1 text-xs text-foreground border border-border">
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
            className="absolute top-4 right-4 w-72 bg-card/95 backdrop-blur-md border border-border rounded-xl p-4 shadow-xl"
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
                <h3 className="text-sm font-semibold text-foreground mt-2">{selectedNode.label}</h3>
              </div>
              <button onClick={() => setSelectedNode(null)} className="text-muted-foreground hover:text-foreground transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="mt-3 space-y-1.5 text-xs text-muted-foreground">
              <div className="flex justify-between">
                <span>Weight</span>
                <span className="text-foreground font-medium">{selectedNode.weight}</span>
              </div>
              {selectedNode.community !== undefined && (
                <div className="flex justify-between">
                  <span>Community</span>
                  <span className="text-foreground font-medium">#{selectedNode.community}</span>
                </div>
              )}
              {"channel" in selectedNode && selectedNode.channel && (
                <div className="flex justify-between">
                  <span>Channel</span>
                  <span className="text-foreground font-medium">{selectedNode.channel}</span>
                </div>
              )}
              {"message_id" in selectedNode && selectedNode.message_id !== undefined && (
                <div className="flex justify-between">
                  <span>Message</span>
                  <span className="text-foreground font-medium">#{selectedNode.message_id}</span>
                </div>
              )}
              {"source_status" in selectedNode && selectedNode.source_status && (
                <div className="flex justify-between">
                  <span>Source</span>
                  <span className="text-foreground font-medium capitalize">{selectedNode.source_status}</span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
