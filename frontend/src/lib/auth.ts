"use client";

import { config } from "./config";
import type { UserTelegramChannel } from "@/types";

const AUTH_BASE = config.authBaseUrl;

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export interface UserProfile {
  id: string;
  email: string;
  username: string;
  role: "admin" | "user";
  is_active: boolean;
  created_at: string;
}

export class AuthApiError extends Error {
  code: string | null;
  meta: Record<string, unknown> | null;
  status: number;

  constructor(message: string, options: { code?: string | null; meta?: Record<string, unknown> | null; status: number }) {
    super(message);
    this.name = "AuthApiError";
    this.code = options.code ?? null;
    this.meta = options.meta ?? null;
    this.status = options.status;
  }
}

const TOKEN_KEY = "tg_access_token";
const REFRESH_KEY = "tg_refresh_token";
const EXPIRES_KEY = "tg_token_expires";

export function getStoredTokens(): { access: string | null; refresh: string | null } {
  if (typeof window === "undefined") return { access: null, refresh: null };
  return {
    access: localStorage.getItem(TOKEN_KEY),
    refresh: localStorage.getItem(REFRESH_KEY),
  };
}

export function storeTokens(tokens: AuthTokens): void {
  localStorage.setItem(TOKEN_KEY, tokens.access_token);
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  localStorage.setItem(EXPIRES_KEY, String(Date.now() + tokens.expires_in * 1000));
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(EXPIRES_KEY);
}

function isTokenExpiringSoon(): boolean {
  const expires = localStorage.getItem(EXPIRES_KEY);
  if (!expires) return true;
  return Date.now() > Number(expires) - 60_000;
}

async function refreshTokens(): Promise<AuthTokens | null> {
  const { refresh } = getStoredTokens();
  if (!refresh) return null;

  try {
    const res = await fetch(`${AUTH_BASE}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) {
      clearTokens();
      return null;
    }
    const tokens: AuthTokens = await res.json();
    storeTokens(tokens);
    return tokens;
  } catch {
    clearTokens();
    return null;
  }
}

let refreshPromise: Promise<AuthTokens | null> | null = null;

export async function getValidAccessToken(): Promise<string | null> {
  const { access } = getStoredTokens();
  if (!access) return null;

  if (!isTokenExpiringSoon()) return access;

  if (!refreshPromise) {
    refreshPromise = refreshTokens().finally(() => {
      refreshPromise = null;
    });
  }
  const result = await refreshPromise;
  return result?.access_token ?? null;
}

async function authFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = await getValidAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${AUTH_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    clearTokens();
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("auth:logout"));
    }
    throw new AuthApiError("Unauthorized", { status: 401 });
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail as
      | { detail?: string; error?: string; meta?: Record<string, unknown> | null }
      | string
      | undefined;
    if (detail && typeof detail === "object") {
      throw new AuthApiError(detail.detail || `API error ${res.status}`, {
        code: detail.error,
        meta: detail.meta ?? null,
        status: res.status,
      });
    }
    throw new AuthApiError(detail || `API error ${res.status}`, { status: res.status });
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const authApi = {
  register(email: string, username: string, password: string): Promise<AuthTokens> {
    return authFetch("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, username, password }),
    });
  },

  login(login: string, password: string): Promise<AuthTokens> {
    return authFetch("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ login, password }),
    });
  },

  logout(): Promise<void> {
    const { refresh } = getStoredTokens();
    clearTokens();
    if (!refresh) return Promise.resolve();
    return authFetch("/api/auth/logout", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refresh }),
    });
  },

  getProfile(): Promise<UserProfile> {
    return authFetch("/api/auth/me");
  },

  updateProfile(data: { username?: string; email?: string }): Promise<UserProfile> {
    return authFetch("/api/auth/me", {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  changePassword(current: string, newPassword: string): Promise<void> {
    return authFetch("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: current, new_password: newPassword }),
    });
  },

  editMessage(eventId: string, changes: Record<string, unknown>): Promise<unknown> {
    return authFetch(`/api/admin/messages/${encodeURIComponent(eventId)}`, {
      method: "PATCH",
      body: JSON.stringify(changes),
    });
  },

  getChannels(): Promise<Array<{ channel_name: string; is_visible: boolean; updated_at: string | null }>> {
    return authFetch("/api/admin/channels");
  },

  setChannelVisibility(channelName: string, isVisible: boolean): Promise<unknown> {
    return authFetch(`/api/admin/channels/${encodeURIComponent(channelName)}`, {
      method: "PUT",
      body: JSON.stringify({ is_visible: isVisible }),
    });
  },

  getAuditLog(limit = 50, offset = 0): Promise<unknown[]> {
    return authFetch(`/api/admin/audit-log?limit=${limit}&offset=${offset}`);
  },

  addReaction(eventId: string, reaction: "like" | "dislike"): Promise<{ status: string; reaction: string | null }> {
    return authFetch(`/api/messages/${encodeURIComponent(eventId)}/reaction`, {
      method: "POST",
      body: JSON.stringify({ reaction }),
    });
  },

  getReactions(eventId: string): Promise<{ message_event_id: string; likes: number; dislikes: number; user_reaction: string | null }> {
    return authFetch(`/api/messages/${encodeURIComponent(eventId)}/reactions`);
  },

  batchReactions(eventIds: string[]): Promise<Array<{ message_event_id: string; likes: number; dislikes: number; user_reaction: string | null }>> {
    return authFetch("/api/messages/batch-reactions", {
      method: "POST",
      body: JSON.stringify(eventIds),
    });
  },

  async forgotPassword(email: string): Promise<{ detail: string }> {
    const res = await fetch(`${AUTH_BASE}/api/auth/forgot-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Error ${res.status}`);
    }
    return res.json();
  },

  async resetPassword(token: string, newPassword: string): Promise<{ detail: string }> {
    const res = await fetch(`${AUTH_BASE}/api/auth/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, new_password: newPassword }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Error ${res.status}`);
    }
    return res.json();
  },

  verifyEmail(token: string): Promise<{ detail: string }> {
    return authFetch("/api/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  },

  resendVerification(): Promise<{ detail: string }> {
    return authFetch("/api/auth/resend-verification", {
      method: "POST",
    });
  },

  addTelegramChannel(channel: string, startDate: string): Promise<UserTelegramChannel> {
    return authFetch("/api/sources/telegram/channels", {
      method: "POST",
      body: JSON.stringify({ channel, start_date: startDate }),
    });
  },

  getTelegramChannels(): Promise<UserTelegramChannel[]> {
    return authFetch("/api/sources/telegram/channels");
  },

  getTelegramChannel(channelName: string): Promise<UserTelegramChannel> {
    return authFetch(`/api/sources/telegram/channels/${encodeURIComponent(channelName)}`);
  },

  getTelegramChannelProgress(channelName: string): Promise<UserTelegramChannel> {
    return authFetch(`/api/sources/telegram/channels/${encodeURIComponent(channelName)}/progress`);
  },
};
