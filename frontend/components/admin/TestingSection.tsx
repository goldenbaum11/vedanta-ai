"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PersonaModel, listModels, testModel } from "@/lib/admin";

interface Exchange {
  prompt: string;
  answer: string;
  model: string;
}

export function TestingSection() {
  const [models, setModels] = useState<PersonaModel[]>([]);
  const [modelId, setModelId] = useState<number | null>(null);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<Exchange[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await listModels();
        if (cancelled) return;
        setModels(res.models);
        // Preselect the newest ready model.
        const ready = res.models.filter((m) => m.status === "ready");
        setModelId((current) => current ?? ready[0]?.id ?? null);
      } catch {
        /* ignore */
      }
    }
    void load();
    const interval = setInterval(load, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const ready = models.filter((m) => m.status === "ready");

  async function ask() {
    if (modelId === null || !prompt.trim() || busy) return;
    const question = prompt.trim();
    const modelName =
      ready.find((m) => m.id === modelId)?.name ?? `model ${modelId}`;
    setBusy(true);
    setError(null);
    try {
      const res = await testModel(modelId, question);
      setHistory((h) => [
        { prompt: question, answer: res.answer, model: modelName },
        ...h,
      ]);
      setPrompt("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (ready.length === 0) {
    return (
      <div className="rounded-lg border border-ink-200 bg-white p-4 text-sm shadow-sm dark:border-ink-700 dark:bg-ink-900">
        <p className="text-ink-500 dark:text-ink-300">
          No trained models yet. Build a dataset and start a run in the{" "}
          <Link
            href="/admin/studio"
            className="text-saffron-700 underline dark:text-saffron-300"
          >
            Training Studio
          </Link>
          , then come back here to try it.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-ink-200 bg-white p-4 shadow-sm dark:border-ink-700 dark:bg-ink-900">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={modelId ?? ""}
            onChange={(e) =>
              setModelId(e.target.value ? Number(e.target.value) : null)
            }
            className="rounded-md border border-ink-200 bg-white px-2 py-1.5 text-sm dark:border-ink-700 dark:bg-ink-950"
          >
            {ready.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.train_pairs} pairs)
              </option>
            ))}
          </select>
          <input
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void ask();
            }}
            placeholder="Ask AI-Jonas something…"
            className="min-w-64 flex-1 rounded-md border border-ink-200 bg-white px-2 py-1.5 text-sm dark:border-ink-700 dark:bg-ink-950"
          />
          <button
            onClick={() => void ask()}
            disabled={busy || !prompt.trim()}
            className="rounded-md bg-saffron-600 px-4 py-1.5 text-sm text-white shadow-sm hover:bg-saffron-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Generating…" : "Ask"}
          </button>
        </div>
        {busy && (
          <p className="mt-2 text-xs text-ink-500 dark:text-ink-400">
            The model loads into memory per question — expect up to ~30s.
          </p>
        )}
        {error && (
          <p className="mt-2 text-sm text-red-700 dark:text-red-400">{error}</p>
        )}
      </div>

      {history.map((ex, i) => (
        <div
          key={history.length - i}
          className="rounded-lg border border-ink-200 bg-white p-4 shadow-sm dark:border-ink-700 dark:bg-ink-900"
        >
          <p className="mb-1 text-xs text-ink-400">{ex.model}</p>
          <p className="mb-2 text-sm font-medium text-saffron-800 dark:text-saffron-300">
            Q: {ex.prompt}
          </p>
          <p className="whitespace-pre-wrap text-sm text-ink-700 dark:text-ink-100">
            {ex.answer}
          </p>
        </div>
      ))}
    </div>
  );
}
