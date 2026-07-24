"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  PersonaModel,
  listModels,
  startTraining,
  testModel,
} from "@/lib/admin";

export function TrainingSection() {
  const [models, setModels] = useState<PersonaModel[]>([]);
  const [name, setName] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [startedJobId, setStartedJobId] = useState<number | null>(null);
  const [testPrompt, setTestPrompt] = useState("");
  const [testModelId, setTestModelId] = useState<number | null>(null);
  const [testAnswer, setTestAnswer] = useState<string | null>(null);
  const [testBusy, setTestBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await listModels();
        if (!cancelled) setModels(res.models);
      } catch {
        /* ignore */
      }
    }
    void load();
    const interval = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  async function handleStart() {
    setMessage(null);
    setStartedJobId(null);
    try {
      const res = await startTraining(name || undefined);
      setMessage(`Training job #${res.job_id} started.`);
      setStartedJobId(res.job_id);
    } catch (err) {
      setMessage(`Could not start: ${(err as Error).message}`);
    }
  }

  async function handleTest() {
    if (testModelId === null || !testPrompt.trim()) return;
    setTestBusy(true);
    setTestAnswer(null);
    try {
      const res = await testModel(testModelId, testPrompt.trim());
      setTestAnswer(res.answer);
    } catch (err) {
      setTestAnswer(`Error: ${(err as Error).message}`);
    } finally {
      setTestBusy(false);
    }
  }

  const ready = models.filter((m) => m.status === "ready");

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
        <h3 className="mb-2 text-sm font-medium text-neutral-300">
          Start a training run
        </h3>
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="model name (default: jonas-vYYYYMMDD-HHMM)"
            className="w-72 rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-sm"
          />
          <button
            onClick={() => void handleStart()}
            className="rounded bg-amber-600 px-4 py-1.5 text-sm text-white hover:bg-amber-500"
          >
            Start training
          </button>
        </div>
        {message && (
          <p className="mt-3 text-sm text-neutral-300">
            {message}{" "}
            {startedJobId !== null && (
              <Link href="/admin/jobs" className="text-amber-400 underline">
                Watch the logs in Jobs →
              </Link>
            )}
          </p>
        )}
        <p className="mt-2 text-xs text-neutral-500">
          Exports all approved pairs, then fine-tunes a LoRA adapter on the
          base model (first run downloads it, ~4 GB). Only one training job
          runs at a time.
        </p>
      </div>

      <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
        <h3 className="mb-2 text-sm font-medium text-neutral-300">Models</h3>
        {models.length === 0 && (
          <p className="text-sm text-neutral-500">No models trained yet.</p>
        )}
        <ul className="space-y-1 text-sm">
          {models.map((m) => (
            <li
              key={m.id}
              className="flex items-center gap-3 rounded bg-neutral-800 px-3 py-2"
            >
              <span
                className={`rounded px-2 py-0.5 text-xs text-white ${
                  m.status === "ready"
                    ? "bg-green-700"
                    : m.status === "training"
                      ? "bg-blue-600"
                      : "bg-red-700"
                }`}
              >
                {m.status}
              </span>
              <span className="font-medium">{m.name}</span>
              <span className="text-xs text-neutral-400">
                {m.train_pairs} train / {m.val_pairs} valid ·{" "}
                {m.base_model.split("/").pop()}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
        <h3 className="mb-2 text-sm font-medium text-neutral-300">
          Test a model
        </h3>
        {ready.length === 0 ? (
          <p className="text-sm text-neutral-500">
            No ready models yet — train one first.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={testModelId ?? ""}
                onChange={(e) =>
                  setTestModelId(e.target.value ? Number(e.target.value) : null)
                }
                className="rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-sm"
              >
                <option value="">choose model…</option>
                {ready.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
              <input
                type="text"
                value={testPrompt}
                onChange={(e) => setTestPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleTest();
                }}
                placeholder="Ask AI-Jonas something…"
                className="min-w-64 flex-1 rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-sm"
              />
              <button
                onClick={() => void handleTest()}
                disabled={testBusy || testModelId === null}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-500 disabled:opacity-50"
              >
                {testBusy ? "Generating…" : "Ask"}
              </button>
            </div>
            {testBusy && (
              <p className="mt-2 text-xs text-neutral-500">
                First question loads the model into memory — up to ~30s.
              </p>
            )}
            {testAnswer && (
              <p className="mt-3 whitespace-pre-wrap rounded bg-neutral-800 p-3 text-sm text-neutral-200">
                {testAnswer}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
