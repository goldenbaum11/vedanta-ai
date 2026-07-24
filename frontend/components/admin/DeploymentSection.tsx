"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ActiveDeployment,
  DeploymentHistoryEntry,
  PersonaModel,
  deactivateDeployment,
  deployModel,
  getDeployment,
  listModels,
} from "@/lib/admin";

export function DeploymentSection() {
  const [active, setActive] = useState<ActiveDeployment | null>(null);
  const [history, setHistory] = useState<DeploymentHistoryEntry[]>([]);
  const [models, setModels] = useState<PersonaModel[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [dep, mods] = await Promise.all([getDeployment(), listModels()]);
      setActive(dep.active);
      setHistory(dep.history);
      setModels(mods.models);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, [load]);

  async function handleDeploy(model: PersonaModel) {
    setBusy(true);
    setMessage(null);
    try {
      await deployModel(model.id);
      setMessage(`${model.name} is now live in chat.`);
      await load();
    } catch (err) {
      setMessage(`Deploy failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleRollback() {
    setBusy(true);
    setMessage(null);
    try {
      await deactivateDeployment();
      setMessage("Rolled back — chat uses the stock agent pipeline again.");
      await load();
    } catch (err) {
      setMessage(`Rollback failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const ready = models.filter((m) => m.status === "ready");

  return (
    <div className="space-y-6">
      {/* Current state */}
      <div
        className={`rounded-lg border p-4 ${
          active
            ? "border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-950/30"
            : "border-ink-200 bg-white dark:border-ink-700 dark:bg-ink-900"
        }`}
      >
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
          Currently live in chat
        </p>
        {active ? (
          <>
            <p className="mt-1 text-lg font-medium text-green-800 dark:text-green-300">
              {active.name}
            </p>
            <p className="mt-1 text-sm text-ink-600 dark:text-ink-300">
              LoRA adapter on {active.base_model.split("/").pop()} ·{" "}
              {active.train_pairs} training pairs · deployed{" "}
              {new Date(active.created_at).toLocaleString()}
            </p>
            <button
              onClick={() => void handleRollback()}
              disabled={busy}
              className="mt-3 rounded-md bg-ink-800 px-4 py-1.5 text-sm text-white hover:bg-ink-700 disabled:opacity-50 dark:bg-ink-100 dark:text-ink-900 dark:hover:bg-white"
            >
              Roll back to stock pipeline
            </button>
          </>
        ) : (
          <>
            <p className="mt-1 text-lg font-medium text-ink-900 dark:text-ink-50">
              Stock agent pipeline
            </p>
            <p className="mt-1 text-sm text-ink-500 dark:text-ink-300">
              Chat is answered by the six specialist agents (RAG + local LLM).
              Deploy a trained model below to have AI-Jonas answer instead.
            </p>
          </>
        )}
      </div>

      {message && (
        <p className="text-sm text-ink-700 dark:text-ink-200">{message}</p>
      )}

      {/* Deployable models */}
      <div className="rounded-lg border border-ink-200 bg-white p-4 shadow-sm dark:border-ink-700 dark:bg-ink-900">
        <h3 className="mb-2 text-sm font-medium text-ink-700 dark:text-ink-200">
          Trained models
        </h3>
        {ready.length === 0 ? (
          <p className="text-sm text-ink-500 dark:text-ink-400">
            No deployable models yet — train one in the{" "}
            <Link
              href="/admin/studio"
              className="text-saffron-700 underline dark:text-saffron-300"
            >
              Training Studio
            </Link>
            .
          </p>
        ) : (
          <ul className="space-y-1 text-sm">
            {ready.map((m) => {
              const isLive = active?.model_id === m.id;
              return (
                <li
                  key={m.id}
                  className="flex items-center gap-3 rounded-md bg-ink-50 px-3 py-2 dark:bg-ink-800"
                >
                  <span className="font-medium">{m.name}</span>
                  <span className="text-xs text-ink-500 dark:text-ink-300">
                    {m.train_pairs} train / {m.val_pairs} valid ·{" "}
                    {new Date(m.created_at).toLocaleDateString()}
                  </span>
                  {isLive ? (
                    <span className="ml-auto rounded bg-green-700 px-2 py-0.5 text-xs text-white">
                      live
                    </span>
                  ) : (
                    <button
                      onClick={() => void handleDeploy(m)}
                      disabled={busy}
                      className="ml-auto rounded-md bg-saffron-600 px-3 py-1 text-xs text-white hover:bg-saffron-700 disabled:opacity-50"
                    >
                      Deploy to chat
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <p className="mt-3 text-xs text-ink-500 dark:text-ink-400">
          Note: the deployed model answers via the MLX runtime and reloads per
          message, so replies take noticeably longer than the stock pipeline.
          For production traffic the adapter should be fused and served from
          LM Studio/Ollama — this switch is for live trials.
        </p>
      </div>

      {/* History */}
      {history.length > 0 && (
        <div className="rounded-lg border border-ink-200 bg-white p-4 shadow-sm dark:border-ink-700 dark:bg-ink-900">
          <h3 className="mb-2 text-sm font-medium text-ink-700 dark:text-ink-200">
            Deployment history
          </h3>
          <ul className="space-y-1 text-sm">
            {history.map((d) => (
              <li
                key={d.deployment_id}
                className="flex flex-wrap items-center gap-2 text-ink-600 dark:text-ink-300"
              >
                <span
                  className={`rounded px-2 py-0.5 text-xs ${
                    d.active
                      ? "bg-green-700 text-white"
                      : "bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-400"
                  }`}
                >
                  {d.active ? "live" : "ended"}
                </span>
                <span className="font-medium">{d.name}</span>
                <span className="text-xs">
                  {new Date(d.created_at).toLocaleString()}
                  {d.deactivated_at
                    ? ` → ${new Date(d.deactivated_at).toLocaleString()}`
                    : ""}
                  {d.deployed_by ? ` · by ${d.deployed_by}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
