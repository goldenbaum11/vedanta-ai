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
  snippet?: string | null;
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
    ollama: { reachable: boolean; base_url: string; default_model: string };
    chroma: { reachable: boolean };
    database: { path: string };
  };
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
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
  created_at: string;
}

export async function fetchMessages(
  limit = 50,
): Promise<{ messages: MessageRow[] }> {
  return request<{ messages: MessageRow[] }>(`/api/v1/messages?limit=${limit}`);
}

export const AGENT_LABELS: Record<AgentName, string> = {
  vedic_scholar: "Vedic Scholar",
  sanskrit_grammar: "Sanskrit Grammar",
  communication: "Communication",
  infosec: "InfoSec Guardian",
  survival: "Survival Skills",
  media: "Media Engine",
};
