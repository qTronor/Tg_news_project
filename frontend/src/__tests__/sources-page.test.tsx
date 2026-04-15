import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SourcesPage from "@/app/sources/page";
import { AuthApiError, authApi } from "@/lib/auth";
import type { UserTelegramChannel } from "@/types";

jest.mock("@/components/layout/header", () => ({
  Header: ({ title }: { title: string }) => <div>{title}</div>,
}));

jest.mock("@/components/layout/page-transition", () => ({
  PageTransition: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

jest.mock("@/lib/auth", () => {
  class MockAuthApiError extends Error {
    code: string | null;
    meta: Record<string, unknown> | null;
    status: number;

    constructor(
      message: string,
      options: { code?: string | null; meta?: Record<string, unknown> | null; status: number },
    ) {
      super(message);
      this.code = options.code ?? null;
      this.meta = options.meta ?? null;
      this.status = options.status;
    }
  }

  return {
    AuthApiError: MockAuthApiError,
    authApi: {
      addTelegramChannel: jest.fn(),
      getTelegramChannels: jest.fn(),
    },
  };
});

const mockedAuthApi = authApi as jest.Mocked<typeof authApi>;

function makeChannel(overrides: Partial<UserTelegramChannel> = {}): UserTelegramChannel {
  return {
    channel_name: "alpha_feed",
    input_value: "@alpha_feed",
    telegram_url: "https://t.me/alpha_feed",
    telegram_channel_id: 42,
    requested_start_date: "2026-04-10",
    historical_limit_date: "2026-01-01",
    status: "validating",
    validation_status: "pending",
    validation_error: null,
    live_enabled: false,
    backfill_total_days: 0,
    backfill_completed_days: 0,
    backfill_failed_days: 0,
    backfill_pending_days: 0,
    backfill_running_days: 0,
    backfill_retrying_days: 0,
    backfill_messages_published: 0,
    backfill_last_completed_date: null,
    last_live_collected_at: null,
    added_at: "2026-04-14T09:00:00Z",
    added_by_user_id: "00000000-0000-0000-0000-000000000001",
    first_message_at: null,
    first_message_event_id: null,
    first_message_available: false,
    raw_message_count: 0,
    feed_path: null,
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={client}>
      <SourcesPage />
    </QueryClientProvider>,
  );
}

describe("SourcesPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("submits a new channel successfully", async () => {
    mockedAuthApi.getTelegramChannels
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([makeChannel()]);
    mockedAuthApi.addTelegramChannel.mockResolvedValue(makeChannel());

    renderPage();
    const user = userEvent.setup();

    await user.type(
      screen.getByPlaceholderText("@channel_name or https://t.me/channel_name"),
      "@alpha_feed",
    );
    await user.click(screen.getByRole("button", { name: /submit/i }));

    await waitFor(() => {
      expect(mockedAuthApi.addTelegramChannel).toHaveBeenCalledWith(
        "@alpha_feed",
        expect.stringMatching(/^20\d{2}-\d{2}-\d{2}$/),
      );
    });
    expect(await screen.findByText("alpha_feed")).toBeInTheDocument();
  });

  it("renders duplicate submit error state", async () => {
    mockedAuthApi.getTelegramChannels.mockResolvedValue([]);
    mockedAuthApi.addTelegramChannel.mockRejectedValue(
      new AuthApiError("Already exists", {
        code: "duplicate",
        status: 409,
        meta: { channel_name: "rbc_news" },
      }),
    );

    renderPage();
    const user = userEvent.setup();

    await user.type(
      screen.getByPlaceholderText("@channel_name or https://t.me/channel_name"),
      "@rbc_news",
    );
    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(await screen.findByText(/Channel already exists: rbc_news/i)).toBeInTheDocument();
  });

  it("renders pending validation state from live API", async () => {
    mockedAuthApi.getTelegramChannels.mockResolvedValue([makeChannel()]);

    renderPage();

    expect(await screen.findByText("Validating")).toBeInTheDocument();
    expect(screen.getByText(/Collector has picked up the request/i)).toBeInTheDocument();
    expect(screen.getByText(/Waiting for first data/i)).toBeInTheDocument();
  });

  it("renders progress and feed CTA", async () => {
    mockedAuthApi.getTelegramChannels.mockResolvedValue([
      makeChannel({
        status: "backfilling",
        validation_status: "validated",
        live_enabled: true,
        backfill_total_days: 4,
        backfill_completed_days: 1,
        backfill_pending_days: 2,
        backfill_running_days: 1,
        backfill_retrying_days: 0,
        raw_message_count: 12,
        first_message_at: "2026-04-14T10:00:00Z",
        first_message_available: true,
        feed_path: "/feed?channel=alpha_feed",
      }),
    ]);

    renderPage();

    expect(await screen.findByText("Backfilling")).toBeInTheDocument();
    expect(screen.getByText("1/4")).toBeInTheDocument();
    expect(screen.getByText(/Messages loaded 12/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open in feed/i })).toHaveAttribute(
      "href",
      "/feed?channel=alpha_feed",
    );
  });
});
