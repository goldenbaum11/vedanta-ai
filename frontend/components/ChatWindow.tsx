"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AgentSelector } from "@/components/AgentSelector";
import { AuthBar } from "@/components/AuthBar";
import { TranslationCard } from "@/components/TranslationCard";
import {
  AGENT_LABELS,
  type AgentName,
  type Citation,
  type MessageRow,
  fetchMessages,
  streamChat,
} from "@/lib/api";
import { type AuthProfile, getStoredAuth } from "@/lib/auth";
import { getOrCreateUserId } from "@/lib/user";

interface ChatTurn {
  id: string;
  role: "user" | "assistant" | "error";
  text: string;
  agent?: AgentName;
  confidence?: number;
  citations?: Citation[];
  escalate?: boolean;
  createdAt: string;
  /** True while this assistant turn is still receiving streamed tokens. */
  streaming?: boolean;
}

function uid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

/**
 * Convert one stored DB row (which contains both query and response) into
 * the two ChatTurn entries that render as a question/answer pair.
 */
function rowToTurns(row: MessageRow): ChatTurn[] {
  let citations: Citation[] = [];
  if (row.citations_json) {
    try {
      const parsed = JSON.parse(row.citations_json);
      if (Array.isArray(parsed)) {
        citations = parsed as Citation[];
      }
    } catch {
      // ignore malformed citations from older rows
    }
  }
  const userTurn: ChatTurn = {
    id: `db-${row.id}-q`,
    role: "user",
    text: row.query,
    createdAt: row.created_at,
  };
  const assistantTurn: ChatTurn = {
    id: `db-${row.id}-a`,
    role: "assistant",
    text: row.response,
    agent: row.agent,
    confidence: row.intent_confidence,
    citations,
    createdAt: row.created_at,
  };
  return [userTurn, assistantTurn];
}

export function ChatWindow() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [hydrating, setHydrating] = useState(true);
  const [agentOverride, setAgentOverride] = useState<AgentName | "auto">("auto");
  const [userId, setUserId] = useState<string>("");
  const [authProfile, setAuthProfile] = useState<AuthProfile | null>(
    () => getStoredAuth()?.profile ?? null,
  );
  const scrollRef = useRef<HTMLDivElement>(null);

  // Resolve a stable per-browser id and hydrate previous conversation.
  // The "ownership" key for history is `user:N` when signed in, or the
  // anonymous browser id otherwise. When the user signs in/out we
  // re-hydrate against the appropriate key.
  useEffect(() => {
    const anonId = getOrCreateUserId();
    const effectiveId = authProfile ? `user:${authProfile.id}` : anonId;
    setUserId(effectiveId);
    let cancelled = false;
    setHydrating(true);
    (async () => {
      try {
        const { messages: rows } = await fetchMessages(50, effectiveId);
        if (cancelled) return;
        // DB returns newest-first; we want chronological order in the UI.
        const reversed = [...rows].reverse();
        const restored = reversed.flatMap(rowToTurns);
        setTurns(restored);
      } catch {
        // Backend unreachable on first load; leave turns empty so the
        // user can still type and let the failure surface on submit.
      } finally {
        if (!cancelled) setHydrating(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authProfile]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [turns]);

  const submit = useCallback(async () => {
    const message = input.trim();
    if (!message || busy) return;

    const userTurn: ChatTurn = {
      id: uid(),
      role: "user",
      text: message,
      createdAt: new Date().toISOString(),
    };
    const assistantId = uid();
    const assistantTurn: ChatTurn = {
      id: assistantId,
      role: "assistant",
      text: "",
      createdAt: new Date().toISOString(),
      streaming: true,
    };
    setTurns((prev) => [...prev, userTurn, assistantTurn]);
    setInput("");
    setBusy(true);

    const updateAssistant = (mut: (turn: ChatTurn) => ChatTurn) => {
      setTurns((prev) =>
        prev.map((t) => (t.id === assistantId ? mut(t) : t)),
      );
    };

    try {
      const stream = streamChat({
        message,
        user_id: userId || null,
        agent_override: agentOverride === "auto" ? null : agentOverride,
      });
      for await (const event of stream) {
        switch (event.type) {
          case "intent":
            updateAssistant((t) => ({
              ...t,
              agent: event.agent,
              confidence: event.confidence,
            }));
            break;
          case "meta":
            updateAssistant((t) => ({
              ...t,
              agent: event.agent,
              citations: event.citations,
              escalate: event.escalate,
            }));
            break;
          case "token":
            updateAssistant((t) => ({ ...t, text: t.text + event.delta }));
            break;
          case "done":
            updateAssistant((t) => ({
              ...t,
              text: event.text || t.text,
              createdAt: event.created_at ?? t.createdAt,
              streaming: false,
            }));
            break;
          case "error":
            updateAssistant((t) => ({
              ...t,
              text: event.text || t.text,
              streaming: false,
            }));
            setTurns((prev) => [
              ...prev,
              {
                id: uid(),
                role: "error",
                text: event.message,
                createdAt: new Date().toISOString(),
              },
            ]);
            break;
        }
      }
      // Safety: ensure the streaming flag clears even if no terminal event arrived.
      updateAssistant((t) => (t.streaming ? { ...t, streaming: false } : t));
    } catch (error) {
      updateAssistant((t) => ({ ...t, streaming: false }));
      setTurns((prev) => [
        ...prev,
        {
          id: uid(),
          role: "error",
          text:
            error instanceof Error
              ? error.message
              : "Unknown error contacting the backend.",
          createdAt: new Date().toISOString(),
        },
      ]);
    } finally {
      setBusy(false);
    }
  }, [agentOverride, busy, input, userId]);

  const clearLocalView = useCallback(() => {
    setTurns([]);
  }, []);

  const turnCount = useMemo(() => turns.length, [turns]);

  return (
    <section className="flex h-[calc(100vh-10rem)] flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="font-serif text-2xl font-semibold">Ashram Chat</h1>
        <div className="flex flex-wrap items-center gap-2">
          <AuthBar onAuthStateChange={setAuthProfile} />
          {turnCount > 0 ? (
            <button
              type="button"
              onClick={clearLocalView}
              disabled={busy}
              title="Hides the current view; does not delete server-side history."
              className="rounded-md border border-ink-200 px-2 py-1 text-xs text-ink-600 transition hover:bg-ink-50 disabled:opacity-50 dark:border-ink-700 dark:text-ink-300 dark:hover:bg-ink-800"
            >
              New conversation
            </button>
          ) : null}
          <AgentSelector
            value={agentOverride}
            onChange={setAgentOverride}
            disabled={busy}
          />
        </div>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-lg border border-ink-200 bg-white p-4 shadow-sm dark:border-ink-800 dark:bg-ink-900"
      >
        {hydrating ? (
          <HydratingState />
        ) : turns.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="space-y-4">
            {turns.map((turn) => (
              <li key={turn.id}>
                <TurnBubble turn={turn} />
              </li>
            ))}
          </ul>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        className="flex flex-col gap-2 rounded-lg border border-ink-200 bg-white p-3 shadow-sm dark:border-ink-800 dark:bg-ink-900"
      >
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              void submit();
            }
          }}
          placeholder="Ask about a verse, request a transcription, report an anomaly..."
          rows={3}
          disabled={busy}
          className="w-full resize-none rounded-md border border-ink-200 bg-white p-2 text-sm focus:border-saffron-500 focus:outline-none focus:ring-2 focus:ring-saffron-300 disabled:opacity-50 dark:border-ink-700 dark:bg-ink-950"
        />
        <div className="flex items-center justify-between text-xs text-ink-500">
          <span>Press ⌘/Ctrl + Enter to send</span>
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-md bg-saffron-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-saffron-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Thinking..." : "Send"}
          </button>
        </div>
      </form>
    </section>
  );
}

function TurnBubble({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl bg-saffron-600 px-4 py-2 text-white shadow-sm">
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{turn.text}</p>
        </div>
      </div>
    );
  }
  if (turn.role === "error") {
    return (
      <div className="flex justify-start">
        <div className="max-w-[85%] rounded-2xl border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-800 dark:border-red-700/70 dark:bg-red-900/30 dark:text-red-200">
          <span className="font-medium">Error: </span>
          {turn.text}
        </div>
      </div>
    );
  }
  const showThinking = turn.streaming && !turn.text;
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-2xl border border-ink-200 bg-ink-50 px-4 py-3 text-sm text-ink-900 shadow-sm dark:border-ink-700 dark:bg-ink-800 dark:text-ink-50">
        <div className="mb-1 flex items-center gap-2 text-[11px] uppercase tracking-wide text-ink-500">
          <span className="rounded-full bg-saffron-100 px-2 py-0.5 font-semibold text-saffron-800 dark:bg-saffron-900/40 dark:text-saffron-200">
            {turn.agent ? AGENT_LABELS[turn.agent] : "Assistant"}
          </span>
          {typeof turn.confidence === "number" ? (
            <span>confidence {(turn.confidence * 100).toFixed(0)}%</span>
          ) : null}
          {turn.escalate ? (
            <span className="rounded bg-red-100 px-2 py-0.5 font-semibold text-red-800 dark:bg-red-900/40 dark:text-red-200">
              escalate
            </span>
          ) : null}
          {turn.streaming ? (
            <span className="rounded bg-saffron-50 px-2 py-0.5 font-mono text-[10px] text-saffron-700 dark:bg-saffron-900/30 dark:text-saffron-200">
              streaming
            </span>
          ) : null}
        </div>
        {showThinking ? (
          <ThinkingDots />
        ) : (
          <p className="whitespace-pre-wrap leading-relaxed">
            {turn.text}
            {turn.streaming ? (
              <span className="ml-0.5 inline-block w-2 animate-pulse bg-ink-400 dark:bg-ink-300">
                &nbsp;
              </span>
            ) : null}
          </p>
        )}
        {turn.citations && turn.citations.length > 0 ? (
          <TranslationCard citations={turn.citations} />
        ) : null}
      </div>
    </div>
  );
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 text-ink-400" aria-label="Retrieving and thinking">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current" />
    </div>
  );
}

function HydratingState() {
  return (
    <div className="flex h-full items-center justify-center text-sm text-ink-500">
      Loading recent conversation…
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-ink-500">
      <span aria-hidden className="text-4xl">
        ॐ
      </span>
      <p className="font-serif text-lg">Welcome to Vedanta AI.</p>
      <p className="max-w-md text-sm">
        Ask anything across sacred texts, communication, security, survival
        skills, or media. The router will pick an agent automatically — or
        select one above.
      </p>
    </div>
  );
}
