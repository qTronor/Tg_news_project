import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import TopicReviewPage from "@/app/review/topics/page";

jest.mock("@/components/layout/header", () => ({
  Header: ({ title }: { title: string }) => <div>{title}</div>,
}));

jest.mock("@/components/layout/page-transition", () => ({
  PageTransition: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

jest.mock("@/components/feed/message-card", () => ({
  MessageCard: ({ message }: { message: { text: string } }) => <div>{message.text}</div>,
}));

jest.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({ user: { id: "550e8400-e29b-41d4-a716-446655440000", username: "analyst" } }),
}));

jest.mock("@/lib/use-data", () => ({
  useTopicReviewTasks: () => ({
    data: [
      {
        id: "task-1",
        cluster_id: "run:1",
        run_id: "run",
        reason: "low_confidence",
        status: "pending",
        priority: 80,
        signals: { confidence_score: 0.42 },
        requested_by: null,
        assigned_to: null,
        created_at: "2026-05-03T00:00:00Z",
        updated_at: null,
        completed_at: null,
        active_label: null,
        label_source: null,
        label_status: null,
        topic: {
          cluster_id: "run:1",
          label: "Ставка ЦБ",
          message_count: 12,
          channel_count: 3,
          avg_sentiment: 0.1,
          top_entities: [{ id: "ORG:cb", text: "ЦБ", type: "ORG", mention_count: 4 }],
          top_keywords: ["ставка", "банк"],
          is_new: true,
          first_seen: "2026-05-03T00:00:00Z",
          last_seen: "2026-05-03T01:00:00Z",
          sparkline: [],
          channels: [],
          representative_messages: [
            {
              event_id: "e1",
              channel: "rbc",
              message_id: 1,
              text: "ЦБ сохранил ключевую ставку",
              date: "2026-05-03T00:00:00Z",
              views: 10,
              forwards: 1,
            },
          ],
          related_topics: [],
          sentiment_breakdown: { positive: 1, neutral: 1, negative: 0 },
          volume_timeline: [],
          confidence_score: 0.42,
          stability_score: 0.7,
        },
      },
    ],
    isLoading: false,
    isFetching: false,
  }),
  useTopicReviewTask: () => ({
    data: null,
    isLoading: false,
  }),
}));

describe("TopicReviewPage", () => {
  it("renders review task, evidence and actions", () => {
    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <TopicReviewPage />
      </QueryClientProvider>
    );

    expect(screen.getByText("Проверка тем")).toBeTruthy();
    expect(screen.getAllByText("Ставка ЦБ").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Низкая уверенность").length).toBeGreaterThan(0);
    expect(screen.getByText("ЦБ сохранил ключевую ставку")).toBeTruthy();
    expect(screen.getByText("Подтвердить")).toBeTruthy();
    expect(screen.getByText("Переименовать")).toBeTruthy();
    expect(screen.getByText("Объединить")).toBeTruthy();
    expect(screen.getByText("Разделить")).toBeTruthy();
  });
});
