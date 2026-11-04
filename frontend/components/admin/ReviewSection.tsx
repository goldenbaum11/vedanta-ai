"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Pair, listPairs, updatePair } from "@/lib/admin";

const PAGE_SIZE = 50;

export function ReviewSection() {
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState({ question: "", answer: "" });
  // How many pairs are currently loaded, kept in a ref so the periodic
  // auto-refresh can re-fetch exactly that many without resetting
  // progress a reviewer made by clicking "Load more".
  const loadedCountRef = useRef(PAGE_SIZE);

  const refresh = useCallback(async () => {
    try {
      const res = await listPairs({
        status: statusFilter || undefined,
        limit: loadedCountRef.current,
      });
      setPairs(res.pairs);
      setTotal(res.total);
    } catch {
      /* ignore */
    }
  }, [statusFilter]);

  useEffect(() => {
    loadedCountRef.current = PAGE_SIZE;
    void refresh();
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, [refresh]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const res = await listPairs({
        status: statusFilter || undefined,
        offset: pairs.length,
        limit: PAGE_SIZE,
      });
      setPairs((prev) => [...prev, ...res.pairs]);
      setTotal(res.total);
      loadedCountRef.current += res.pairs.length;
    } catch {
      /* ignore */
    } finally {
      setLoadingMore(false);
    }
  }

  async function setStatus(id: number, status: string) {
    await updatePair(id, { status });
    await refresh();
  }

  async function saveEdit(id: number) {
    await updatePair(id, { question: draft.question, answer: draft.answer });
    setEditing(null);
    await refresh();
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        {["pending", "approved", "rejected", ""].map((s) => (
          <button
            key={s || "all"}
            onClick={() => setStatusFilter(s)}
            className={`rounded-md px-3 py-1 transition ${
              statusFilter === s
                ? "bg-saffron-600 text-white shadow-sm"
                : "bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-ink-800 dark:text-ink-200 dark:hover:bg-ink-700"
            }`}
          >
            {s || "all"}
          </button>
        ))}
        <span className="ml-auto text-xs text-ink-500 dark:text-ink-400">
          showing {pairs.length} of {total}
        </span>
      </div>
      <div className="space-y-3">
        {pairs.length === 0 && (
          <p className="text-sm text-ink-500 dark:text-ink-400">
            Nothing here — upload a transcript or switch the filter above.
          </p>
        )}
        {pairs.map((pair) => (
          <div
            key={pair.id}
            className="rounded-lg border border-ink-200 bg-white p-4 shadow-sm dark:border-ink-700 dark:bg-ink-900"
          >
            {editing === pair.id ? (
              <div className="space-y-2">
                <textarea
                  value={draft.question}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, question: e.target.value }))
                  }
                  className="w-full rounded-md border border-ink-200 bg-white p-2 text-sm dark:border-ink-700 dark:bg-ink-950"
                  rows={2}
                />
                <textarea
                  value={draft.answer}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, answer: e.target.value }))
                  }
                  className="w-full rounded-md border border-ink-200 bg-white p-2 text-sm dark:border-ink-700 dark:bg-ink-950"
                  rows={8}
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => void saveEdit(pair.id)}
                    className="rounded-md bg-saffron-600 px-3 py-1 text-sm text-white hover:bg-saffron-700"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => setEditing(null)}
                    className="rounded-md bg-ink-100 px-3 py-1 text-sm hover:bg-ink-200 dark:bg-ink-700 dark:hover:bg-ink-600"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <>
                <p className="mb-2 text-sm font-medium text-saffron-800 dark:text-saffron-300">
                  Q: {pair.question}
                </p>
                <p className="whitespace-pre-wrap text-sm text-ink-700 dark:text-ink-100">
                  {pair.answer}
                </p>
                <div className="mt-3 flex items-center gap-2 text-sm">
                  <button
                    onClick={() => void setStatus(pair.id, "approved")}
                    className="rounded-md bg-green-700 px-3 py-1 text-white hover:bg-green-600"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => void setStatus(pair.id, "rejected")}
                    className="rounded-md bg-red-700 px-3 py-1 text-white hover:bg-red-600"
                  >
                    Reject
                  </button>
                  <button
                    onClick={() => {
                      setEditing(pair.id);
                      setDraft({
                        question: pair.question,
                        answer: pair.answer,
                      });
                    }}
                    className="rounded-md bg-ink-100 px-3 py-1 hover:bg-ink-200 dark:bg-ink-700 dark:hover:bg-ink-600"
                  >
                    Edit
                  </button>
                  <span className="ml-auto text-xs text-ink-500 dark:text-ink-400">
                    #{pair.id} · {pair.kind} ·{" "}
                    {pair.answer.split(/\s+/).length} words · {pair.status}
                    {pair.reviewed_by ? ` · reviewed by ${pair.reviewed_by}` : ""}
                  </span>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
      {pairs.length < total && (
        <button
          onClick={() => void loadMore()}
          disabled={loadingMore}
          className="mt-3 w-full rounded-md bg-ink-100 px-3 py-2 text-sm hover:bg-ink-200 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-ink-800 dark:hover:bg-ink-700"
        >
          {loadingMore ? "Loading…" : `Load ${Math.min(PAGE_SIZE, total - pairs.length)} more`}
        </button>
      )}
    </div>
  );
}
