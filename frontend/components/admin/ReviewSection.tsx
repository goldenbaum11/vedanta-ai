"use client";

import { useCallback, useEffect, useState } from "react";
import { Pair, listPairs, updatePair } from "@/lib/admin";

export function ReviewSection() {
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState({ question: "", answer: "" });

  const load = useCallback(async () => {
    try {
      const res = await listPairs({ status: statusFilter || undefined });
      setPairs(res.pairs);
    } catch {
      /* ignore */
    }
  }, [statusFilter]);

  useEffect(() => {
    void load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, [load]);

  async function setStatus(id: number, status: string) {
    await updatePair(id, { status });
    await load();
  }

  async function saveEdit(id: number) {
    await updatePair(id, { question: draft.question, answer: draft.answer });
    setEditing(null);
    await load();
  }

  return (
    <div>
      <div className="mb-3 flex gap-2 text-sm">
        {["pending", "approved", "rejected", ""].map((s) => (
          <button
            key={s || "all"}
            onClick={() => setStatusFilter(s)}
            className={`rounded px-3 py-1 ${
              statusFilter === s
                ? "bg-amber-600 text-white"
                : "bg-neutral-800 text-neutral-300 hover:bg-neutral-700"
            }`}
          >
            {s || "all"}
          </button>
        ))}
      </div>
      <div className="space-y-3">
        {pairs.length === 0 && (
          <p className="text-sm text-neutral-500">
            Nothing here — upload a transcript or switch the filter above.
          </p>
        )}
        {pairs.map((pair) => (
          <div
            key={pair.id}
            className="rounded-lg border border-neutral-700 bg-neutral-900 p-4"
          >
            {editing === pair.id ? (
              <div className="space-y-2">
                <textarea
                  value={draft.question}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, question: e.target.value }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 p-2 text-sm"
                  rows={2}
                />
                <textarea
                  value={draft.answer}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, answer: e.target.value }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 p-2 text-sm"
                  rows={8}
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => void saveEdit(pair.id)}
                    className="rounded bg-amber-600 px-3 py-1 text-sm text-white"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => setEditing(null)}
                    className="rounded bg-neutral-700 px-3 py-1 text-sm"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <>
                <p className="mb-2 text-sm font-medium text-amber-300">
                  Q: {pair.question}
                </p>
                <p className="whitespace-pre-wrap text-sm text-neutral-200">
                  {pair.answer}
                </p>
                <div className="mt-3 flex items-center gap-2 text-sm">
                  <button
                    onClick={() => void setStatus(pair.id, "approved")}
                    className="rounded bg-green-700 px-3 py-1 text-white hover:bg-green-600"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => void setStatus(pair.id, "rejected")}
                    className="rounded bg-red-800 px-3 py-1 text-white hover:bg-red-700"
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
                    className="rounded bg-neutral-700 px-3 py-1 hover:bg-neutral-600"
                  >
                    Edit
                  </button>
                  <span className="ml-auto text-xs text-neutral-500">
                    #{pair.id} · {pair.kind} ·{" "}
                    {pair.answer.split(/\s+/).length} words · {pair.status}
                  </span>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
