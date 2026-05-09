export type AgentName =
  | "vedic_scholar"
  | "sanskrit_grammar"
  | "communication"
  | "infosec"
  | "survival"
  | "media";

export interface Citation {
  id?: string | null;
  source?: string | null;
  chapter?: string | null;
  verse?: string | null;
  language?: string | null;
  commentary_author?: string | null;
  tradition?: string | null;
  snippet?: string | null;
  full_text?: string | null;
  distance?: number | null;
}

export interface ChatResponse {
  agent: AgentName;
  text: string;
  intent_confidence: number;
  citations: Citation[];
  metadata: Record<string, unknown>;
  escalate: boolean;
  created_at: string;
}

export interface ChatRequest {
  message: string;
  user_id?: string | null;
  agent_override?: AgentName | null;
}

export interface HealthResponse {
  status: string;
  phase: number;
  dependencies: {
    llm: {
      provider: string;
      reachable: boolean;
      base_url: string;
      default_model: string;
    };
    embeddings?: {
      provider: string;
      model: string;
    };
    chroma: {
      reachable: boolean;
      collections?: Record<string, number>;
    };
    database: { path: string };
  };
}

import { authHeaders } from "@/lib/auth";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(
      `API ${response.status} ${response.statusText}${detail ? `: ${detail}` : ""}`,
    );
  }
  return (await response.json()) as T;
}

export async function sendChat(payload: ChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>("/api/v1/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Discriminated union of events emitted by `POST /api/v1/chat/stream`.
 * The wire format is newline-delimited JSON; each parsed line matches
 * one of these shapes.
 */
export type StreamEvent =
  | { type: "intent"; agent: AgentName; confidence: number; rationale: string | null }
  | {
      type: "meta";
      agent: AgentName;
      citations: Citation[];
      escalate: boolean;
      metadata: Record<string, unknown>;
    }
  | { type: "token"; delta: string }
  | {
      type: "done";
      text: string;
      created_at?: string;
      incomplete?: boolean;
    }
  | { type: "error"; message: string; text?: string };

/**
 * Stream chat tokens from the backend. Yields parsed events as they
 * arrive, terminating after the first `done` or `error` event.
 *
 * Caller should `await for` to consume; pass an `AbortSignal` to allow
 * the user to cancel mid-flight (e.g. browser unmount).
 */
export async function* streamChat(
  payload: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent, void, void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => "");
    throw new Error(
      `Stream ${response.status} ${response.statusText}${detail ? `: ${detail}` : ""}`,
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newlineIdx = buffer.indexOf("\n");
      while (newlineIdx >= 0) {
        const line = buffer.slice(0, newlineIdx).trim();
        buffer = buffer.slice(newlineIdx + 1);
        if (line) {
          try {
            yield JSON.parse(line) as StreamEvent;
          } catch {
            // Drop malformed lines; the next clean event will flush state.
          }
        }
        newlineIdx = buffer.indexOf("\n");
      }
    }
    if (buffer.trim()) {
      try {
        yield JSON.parse(buffer.trim()) as StreamEvent;
      } catch {
        // ignore malformed trailing fragment
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export async function fetchAgents(): Promise<{ agents: AgentName[] }> {
  return request<{ agents: AgentName[] }>("/api/v1/agents");
}

export interface MessageRow {
  id: number;
  user_id: string | null;
  agent: AgentName;
  intent_confidence: number;
  query: string;
  response: string;
  metadata_json: string | null;
  citations_json: string | null;
  created_at: string;
}

export async function fetchMessages(
  limit = 50,
  userId?: string | null,
): Promise<{ messages: MessageRow[] }> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (userId) {
    params.set("user_id", userId);
  }
  return request<{ messages: MessageRow[] }>(
    `/api/v1/messages?${params.toString()}`,
  );
}

export const AGENT_LABELS: Record<AgentName, string> = {
  vedic_scholar: "Vedic Scholar",
  sanskrit_grammar: "Sanskrit Grammar",
  communication: "Communication",
  infosec: "InfoSec Guardian",
  survival: "Survival Skills",
  media: "Media Engine",
};

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: { id: number; email: string; role: string };
}

export async function registerUser(
  email: string,
  password: string,
): Promise<TokenResponse> {
  return request<TokenResponse>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function loginUser(
  email: string,
  password: string,
): Promise<TokenResponse> {
  return request<TokenResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function fetchMe(): Promise<{ id: number; email: string; role: string }> {
  return request<{ id: number; email: string; role: string }>("/api/v1/auth/me");
}
