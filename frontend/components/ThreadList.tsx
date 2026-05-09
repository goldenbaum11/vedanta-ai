"use client";

import { useEffect, useState } from "react";

import { type ThreadSummary, fetchThreads } from "@/lib/api";
import { onAuthChange } from "@/lib/auth";

interface Props {
  /** Currently selected thread (null = "new conversation"). */
  activeThreadId: string | null;
  /** Called when the user clicks a thread or "New conversation". */
  onSelect: (threadId: string | null) => void;
  /**
   * Bumped by the parent whenever a chat turn might have created a
   * new thread, so the sidebar refetches.
   */
  refreshKey: number;
}

function relativeTime(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function ThreadList({ activeThreadId, onSelect, refreshKey }: Props) {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const unsub = onAuthChange(() => setVersion((v) => v + 1));
    return () => {
      unsub();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const { threads: rows } = await fetchThreads(50);
        if (!cancelled) setThreads(rows);
      } catch {
        if (!cancelled) setThreads([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshKey, version]);

  return (
    <aside className="flex h-full w-full flex-col gap-2 overflow-hidden">
      <div className="flex items-center justify-between px-1 text-xs uppercase tracking-wide text-ink-500">
        <span>Conversations</span>
        <button
          type="button"
          onClick={() => onSelect(null)}
          className={`rounded-md border px-2 py-1 text-xs transition ${
            activeThreadId === null
              ? "border-saffron-500 bg-saffron-50 text-saffron-800 dark:bg-saffron-900/30 dark:text-saffron-200"
              : "border-ink-200 hover:bg-ink-50 dark:border-ink-700 dark:hover:bg-ink-800"
          }`}
        >
          + New
        </button>
      </div>
      <div className="flex-1 overflow-y-auto rounded-lg border border-ink-200 bg-white shadow-sm dark:border-ink-800 dark:bg-ink-900">
        {loading ? (
          <p className="p-3 text-xs text-ink-500">Loading…</p>
        ) : threads.length === 0 ? (
          <p className="p-3 text-xs text-ink-500">
            No threads yet. Send a message to start one.
          </p>
        ) : (
          <ul className="divide-y divide-ink-100 dark:divide-ink-800">
            {threads.map((t) => {
              const isActive = activeThreadId === t.thread_id;
              return (
                <li key={t.thread_id}>
                  <button
                    type="button"
                    onClick={() => onSelect(t.thread_id)}
                    className={`flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left transition ${
                      isActive
                        ? "bg-saffron-50 text-saffron-900 dark:bg-saffron-900/30 dark:text-saffron-100"
                        : "hover:bg-ink-50 dark:hover:bg-ink-800"
                    }`}
                  >
                    <span className="line-clamp-1 text-sm font-medium">
                      {t.title || "Untitled"}
                    </span>
                    <span className="flex w-full items-center justify-between text-[11px] text-ink-500">
                      <span>{relativeTime(t.last_active_at)}</span>
                      <span>
                        {t.message_count} · {t.last_agent ?? "—"}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
