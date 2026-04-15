import { render, screen } from "@testing-library/react";
import { SourcePanel } from "@/components/topics/source-panel";
import type { FirstSourcePayload } from "@/types";

function makePayload(status: FirstSourcePayload["source_status"]): FirstSourcePayload {
  return {
    cluster_id: "demo:1",
    source_status: status,
    exact_source:
      status === "exact"
        ? {
            resolution_kind: "exact",
            source_type: "exact_forward",
            source_confidence: 1,
            source_event_id: "demo:0",
            source_channel: "AgencyWire",
            source_message_id: 1,
            source_message_date: "2026-04-09T08:00:00Z",
            source_snippet: "Exact source snippet",
            explanation: { summary: "Exact explanation" },
            evidence: {},
          }
        : {
            resolution_kind: "exact",
            source_type: "unknown",
            source_confidence: 0,
            source_event_id: null,
            source_channel: null,
            source_message_id: null,
            source_message_date: null,
            source_snippet: null,
            explanation: { summary: "No exact source" },
            evidence: {},
          },
    inferred_source:
      status === "probable"
        ? {
            resolution_kind: "inferred",
            source_type: "quoted",
            source_confidence: 0.74,
            source_event_id: "demo:2",
            source_channel: "DeskNews",
            source_message_id: 2,
            source_message_date: "2026-04-09T09:00:00Z",
            source_snippet: "Probable source snippet",
            explanation: { summary: "Probable explanation" },
            evidence: {},
          }
        : {
            resolution_kind: "inferred",
            source_type: status === "exact" ? "earliest_in_cluster" : "unknown",
            source_confidence: status === "exact" ? 0.35 : 0,
            source_event_id: status === "exact" ? "demo:0" : null,
            source_channel: status === "exact" ? "AgencyWire" : null,
            source_message_id: status === "exact" ? 1 : null,
            source_message_date: status === "exact" ? "2026-04-09T08:00:00Z" : null,
            source_snippet: status === "exact" ? "Fallback snippet" : null,
            explanation: {
              summary: status === "exact" ? "Fallback explanation" : "No probable source",
            },
            evidence: {},
          },
    display_source:
      status === "exact"
        ? {
            resolution_kind: "exact",
            source_type: "exact_forward",
            source_confidence: 1,
            source_event_id: "demo:0",
            source_channel: "AgencyWire",
            source_message_id: 1,
            source_message_date: "2026-04-09T08:00:00Z",
            source_snippet: "Exact source snippet",
            explanation: { summary: "Exact explanation" },
            evidence: {},
          }
        : status === "probable"
          ? {
              resolution_kind: "inferred",
              source_type: "quoted",
              source_confidence: 0.74,
              source_event_id: "demo:2",
              source_channel: "DeskNews",
              source_message_id: 2,
              source_message_date: "2026-04-09T09:00:00Z",
              source_snippet: "Probable source snippet",
              explanation: { summary: "Probable explanation" },
              evidence: {},
            }
          : null,
    propagation_chain: [],
  };
}

describe("SourcePanel", () => {
  it("renders exact source badge and snippet", () => {
    render(<SourcePanel source={makePayload("exact")} />);

    expect(screen.getByText("Exact")).toBeTruthy();
    expect(screen.getByText("Exact source snippet")).toBeTruthy();
    expect(screen.getByText("Exact explanation")).toBeTruthy();
  });

  it("renders probable source badge and explanation", () => {
    render(<SourcePanel source={makePayload("probable")} />);

    expect(screen.getByText("Probable")).toBeTruthy();
    expect(screen.getByText("Probable source snippet")).toBeTruthy();
    expect(screen.getByText("Probable explanation")).toBeTruthy();
  });

  it("renders unknown fallback state", () => {
    render(<SourcePanel source={makePayload("unknown")} />);

    expect(screen.getByText("Unknown")).toBeTruthy();
    expect(screen.getByText("No source snippet available.")).toBeTruthy();
    expect(screen.getByText("No exact source")).toBeTruthy();
  });
});
