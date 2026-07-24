"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PersonaModel, listModels, startTraining } from "@/lib/admin";

export function TrainingSection() {
  const [models, setModels] = useState<PersonaModel[]>([]);
  const [name, setName] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [startedJobId, setStartedJobId] = useState<number | null>(null);

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

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-ink-200 bg-white p-4 shadow-sm dark:border-ink-700 dark:bg-ink-900">
        <h3 className="mb-2 text-sm font-medium text-ink-700 dark:text-ink-200">
          Start a training run
        </h3>
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="model name (default: jonas-vYYYYMMDD-HHMM)"
            className="w-72 rounded-md border border-ink-200 bg-white px-2 py-1.5 text-sm dark:border-ink-700 dark:bg-ink-950"
          />
          <button
            onClick={() => void handleStart()}
            className="rounded-md bg-saffron-600 px-4 py-1.5 text-sm text-white shadow-sm hover:bg-saffron-700"
          >
            Start training
          </button>
        </div>
        {message && (
          <p className="mt-3 text-sm text-ink-700 dark:text-ink-200">
            {message}{" "}
            {startedJobId !== null && (
              <Link
                href="/admin/studio/jobs"
                className="text-saffron-700 underline dark:text-saffron-300"
              >
                Watch the logs in Jobs →
              </Link>
            )}
          </p>
        )}
        <p className="mt-2 text-xs text-ink-500 dark:text-ink-400">
          Exports all approved pairs, then fine-tunes a LoRA adapter on the
          base model (first run downloads it, ~4 GB). Only one training job
          runs at a time.
        </p>
      </div>

      <div className="rounded-lg border border-ink-200 bg-white p-4 shadow-sm dark:border-ink-700 dark:bg-ink-900">
        <h3 className="mb-2 text-sm font-medium text-ink-700 dark:text-ink-200">
          Model registry
        </h3>
        {models.length === 0 && (
          <p className="text-sm text-ink-500 dark:text-ink-400">
            No models trained yet.
          </p>
        )}
        <ul className="space-y-1 text-sm">
          {models.map((m) => (
            <li
              key={m.id}
              className="flex items-center gap-3 rounded-md bg-ink-50 px-3 py-2 dark:bg-ink-800"
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
              <span className="text-xs text-ink-500 dark:text-ink-300">
                {m.train_pairs} train / {m.val_pairs} valid ·{" "}
                {m.base_model.split("/").pop()}
              </span>
            </li>
          ))}
        </ul>
        {models.some((m) => m.status === "ready") && (
          <p className="mt-3 text-xs text-ink-500 dark:text-ink-400">
            Ready models can be tried in{" "}
            <Link
              href="/admin/testing"
              className="text-saffron-700 underline dark:text-saffron-300"
            >
              Model Testing
            </Link>{" "}
            and put live from{" "}
            <Link
              href="/admin/deployment"
              className="text-saffron-700 underline dark:text-saffron-300"
            >
              Deployment
            </Link>
            .
          </p>
        )}
      </div>
    </div>
  );
}
