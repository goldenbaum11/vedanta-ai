"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DatasetStats, exportDataset, getDatasetStats } from "@/lib/admin";

export function DatasetSection() {
  const [stats, setStats] = useState<DatasetStats | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await getDatasetStats();
        if (!cancelled) setStats(res);
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

  async function handleExport() {
    try {
      const res = await exportDataset();
      setMessage(
        `Exported ${res.train} train + ${res.valid} valid pairs to ${res.dir}`,
      );
    } catch (err) {
      setMessage(`Export failed: ${(err as Error).message}`);
    }
  }

  const approved = stats?.approved ?? 0;
  const target = stats?.target ?? 500;
  const pct = Math.min(100, Math.round((approved / target) * 100));

  return (
    <div className="rounded-lg border border-ink-200 bg-white p-4 shadow-sm dark:border-ink-700 dark:bg-ink-900">
      <div className="mb-2 flex justify-between text-sm">
        <span>
          {approved} approved / {target} target ({pct}%)
        </span>
        <span className="text-ink-500 dark:text-ink-300">
          {stats?.pending ?? 0} pending · {stats?.rejected ?? 0} rejected
        </span>
      </div>
      <div className="mb-4 h-2 overflow-hidden rounded bg-ink-100 dark:bg-ink-800">
        <div
          className="h-full bg-saffron-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      {(stats?.pending ?? 0) > 0 && (
        <p className="mb-3 text-sm text-ink-500 dark:text-ink-300">
          {stats?.pending} pair(s) still waiting in{" "}
          <Link
            href="/admin/review"
            className="text-saffron-700 underline dark:text-saffron-300"
          >
            Review
          </Link>{" "}
          — only approved pairs are exported.
        </p>
      )}
      <button
        onClick={() => void handleExport()}
        className="rounded-md bg-ink-100 px-3 py-1.5 text-sm hover:bg-ink-200 dark:bg-ink-700 dark:hover:bg-ink-600"
      >
        Export dataset (train/valid JSONL)
      </button>
      {message && (
        <p className="mt-3 text-sm text-ink-700 dark:text-ink-200">{message}</p>
      )}
      <p className="mt-3 text-xs text-ink-500 dark:text-ink-400">
        Export happens automatically when training starts — this button is for
        inspecting the files by hand (data/persona/dataset/mlx/).
      </p>
    </div>
  );
}
