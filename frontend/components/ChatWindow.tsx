"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AgentSelector } from "@/components/AgentSelector";
import { TranslationCard } from "@/components/TranslationCard";
import {
  AGENT_LABELS,
  type AgentName,
  type Citation,
  sendChat,
} from "@/lib/api";

interface ChatTurn {
  id: string;
  role: "user" | "assistant" | "error";
  text: string;
  agent?: AgentName;
  confidence?: number;
  citations?: Citation[];
  escalate?: boolean;
  createdAt: string;
}

function uid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function ChatWindow() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [agentOverride, setAgentOverride] = useState<AgentName | "auto">("auto");
  const scrollRef = useRef<HTMLDivElement>(null);

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
    setTurns((prev) => [...prev, userTurn]);
    setInput("");
    setBusy(true);

    try {
      const response = await sendChat({
        message,
        agent_override: agentOverride === "auto" ? null : agentOverride,
      });
      setTurns((prev) => [
        ...prev,
        {
          id: uid(),
          role: "assistant",
          text: response.text,
          agent: response.agent,
          confidence: response.intent_confidence,
          citations: response.citations,
          escalate: response.escalate,
          createdAt: response.created_at,
        },
      ]);
    } catch (error) {
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
  }, [agentOverride, busy, input]);

  return (
    <section className="flex h-[calc(100vh-10rem)] flex-col gap-3">
      <div className="flex items-center justify-between">
        <h1 className="font-serif text-2xl font-semibold">Ashram Chat</h1>
        <AgentSelector value={agentOverride} onChange={setAgentOverride} disabled={busy} />
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-lg border border-ink-200 bg-white p-4 shadow-sm dark:border-ink-800 dark:bg-ink-900"
      >
        {turns.length === 0 ? (
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
        </div>
        <p className="whitespace-pre-wrap leading-relaxed">{turn.text}</p>
        {turn.citations && turn.citations.length > 0 ? (
          <TranslationCard citations={turn.citations} />
        ) : null}
      </div>
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
