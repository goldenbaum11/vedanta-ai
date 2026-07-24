"use client";

/**
 * Admin console: the persona data pipeline.
 *
 * Sections:
 *  1. Upload      — drop a transcript, extraction starts automatically
 *  2. Jobs        — live status + streaming logs (polled)
 *  3. Review      — approve / reject / edit extracted Q&A pairs
 *  4. Dataset     — progress toward the training target, export
 *  5. Training    — start a LoRA run, watch logs, test ready models
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DatasetStats,
  Job,
  Pair,
  PersonaModel,
  Transcript,
  exportDataset,
  getDatasetStats,
  getJob,
  listJobs,
  listModels,
  listPairs,
  listTranscripts,
  startTraining,
  testModel,
  updatePair,
  uploadTranscript,
} from "@/lib/admin";
import { getAuthProfile, onAuthChange } from "@/lib/auth";

const POLL_MS = 2500;

export default function AdminPage() {
  const [role, setRole] = useState<string | null>(null);

  useEffect(() => {
    setRole(getAuthProfile()?.role ?? null);
    return onAuthChange((auth) => setRole(auth?.profile.role ?? null));
  }, []);

  if (role === null) {
    return (
      <Shell>
        <p className="text-neutral-400">
          Sign in with an admin account to use this page (use the main chat
          page to log in, then come back).
        </p>
      </Shell>
    );
  }
  if (role !== "admin") {
    return (
      <Shell>
        <p className="text-red-400">
          Your account does not have the admin role. Promote it with{" "}
          <code className="text-neutral-300">
            python3 scripts/make_admin.py --email you@example.com
          </code>{" "}
          and sign in again.
        </p>
      </Shell>
    );
  }
  return (
    <Shell>
      <AdminConsole />
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8 text-neutral-100">
      <h1 className="mb-1 text-2xl font-semibold">Persona pipeline</h1>
      <p className="mb-8 text-sm text-neutral-400">
        Transcripts → extraction → review → dataset → LoRA training
      </p>
      {children}
    </main>
  );
}

function AdminConsole() {
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<DatasetStats | null>(null);
  const [models, setModels] = useState<PersonaModel[]>([]);
  const [refreshTick, setRefreshTick] = useState(0);

  const refresh = useCallback(() => setRefreshTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [t, j, s, m] = await Promise.all([
          listTranscripts(),
          listJobs(),
          getDatasetStats(),
          listModels(),
        ]);
        if (cancelled) return;
        setTranscripts(t.transcripts);
        setJobs(j.jobs);
        setStats(s);
        setModels(m.models);
      } catch {
        /* transient poll errors are fine */
      }
    }
    void load();
    const hasActive = jobs.some(
      (j) => j.status === "running" || j.status === "queued",
    );
    const interval = setInterval(load, hasActive ? POLL_MS : POLL_MS * 4);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  return (
    <div className="space-y-10">
      <UploadSection onUploaded={refresh} />
      <JobsSection jobs={jobs} />
      <ReviewSection transcripts={transcripts} onChanged={refresh} />
      <DatasetSection stats={stats} />
      <TrainingSection models={models} onStarted={refresh} />
    </div>
  );
}

/* ---------- 1. Upload ---------- */

function UploadSection({ onUploaded }: { onUploaded: () => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [speaker, setSpeaker] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setMessage(null);
    try {
      for (const file of Array.from(files)) {
        const content = await file.text();
        const res = await uploadTranscript(
          file.name,
          content,
          speaker || undefined,
        );
        setMessage(
          `Uploaded ${file.name} — extraction job #${res.job_id} started. ` +
            `Speakers: ${res.speakers.join(", ")}`,
        );
      }
      onUploaded();
    } catch (err) {
      setMessage(`Upload failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <section>
      <h2 className="mb-3 text-lg font-medium">1 · Upload transcript</h2>
      <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".txt"
            multiple
            disabled={busy}
            onChange={(e) => void handleFiles(e.target.files)}
            className="text-sm file:mr-3 file:rounded file:border-0 file:bg-amber-600 file:px-3 file:py-1.5 file:text-sm file:text-white hover:file:bg-amber-500"
          />
          <input
            type="text"
            value={speaker}
            onChange={(e) => setSpeaker(e.target.value)}
            placeholder="Speaker label (default: Jonas M)"
            className="rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-sm"
          />
          {busy && <span className="text-sm text-neutral-400">Uploading…</span>}
        </div>
        {message && (
          <p className="mt-3 text-sm text-neutral-300">{message}</p>
        )}
        <p className="mt-2 text-xs text-neutral-500">
          Speaker-labelled .txt transcripts. Extraction starts immediately and
          appears in Jobs below; pairs land in Review when done.
        </p>
      </div>
    </section>
  );
}

/* ---------- 2. Jobs ---------- */

function JobsSection({ jobs }: { jobs: Job[] }) {
  const [openJob, setOpenJob] = useState<number | null>(null);
  const [log, setLog] = useState("");
  const logRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (openJob === null) return;
    let cancelled = false;
    async function poll() {
      try {
        const job = await getJob(openJob!);
        if (!cancelled) setLog(job.log ?? "");
      } catch {
        /* ignore */
      }
    }
    void poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [openJob]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [log]);

  const badge = (status: Job["status"]) =>
    ({
      queued: "bg-neutral-600",
      running: "bg-blue-600 animate-pulse",
      succeeded: "bg-green-700",
      failed: "bg-red-700",
    })[status];

  return (
    <section>
      <h2 className="mb-3 text-lg font-medium">2 · Jobs</h2>
      <div className="rounded-lg border border-neutral-700 bg-neutral-900">
        {jobs.length === 0 && (
          <p className="p-4 text-sm text-neutral-500">No jobs yet.</p>
        )}
        <ul className="divide-y divide-neutral-800">
          {jobs.map((job) => (
            <li key={job.id} className="p-3">
              <button
                onClick={() =>
                  setOpenJob(openJob === job.id ? null : job.id)
                }
                className="flex w-full items-center gap-3 text-left text-sm"
              >
                <span
                  className={`rounded px-2 py-0.5 text-xs text-white ${badge(job.status)}`}
                >
                  {job.status}
                </span>
                <span className="font-medium">
                  #{job.id} {job.kind}
                  {job.model_name ? ` · ${job.model_name}` : ""}
                  {job.transcript_id ? ` · transcript ${job.transcript_id}` : ""}
                </span>
                <span className="ml-auto text-xs text-neutral-500">
                  {new Date(job.created_at).toLocaleString()}
                </span>
              </button>
              {job.error && (
                <p className="mt-1 text-xs text-red-400">{job.error}</p>
              )}
              {openJob === job.id && (
                <pre
                  ref={logRef}
                  className="mt-2 max-h-64 overflow-auto rounded bg-black p-3 text-xs leading-relaxed text-green-300"
                >
                  {log || "(no output yet)"}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ---------- 3. Review ---------- */

function ReviewSection({
  transcripts,
  onChanged,
}: {
  transcripts: Transcript[];
  onChanged: () => void;
}) {
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
  }, [load, transcripts]);

  async function setStatus(id: number, status: string) {
    await updatePair(id, { status });
    await load();
    onChanged();
  }

  async function saveEdit(id: number) {
    await updatePair(id, { question: draft.question, answer: draft.answer });
    setEditing(null);
    await load();
  }

  return (
    <section>
      <h2 className="mb-3 text-lg font-medium">3 · Review pairs</h2>
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
            Nothing here — upload a transcript or switch the filter.
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
                    #{pair.id} · {pair.kind} · {pair.answer.split(/\s+/).length}{" "}
                    words · {pair.status}
                  </span>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---------- 4. Dataset ---------- */

function DatasetSection({ stats }: { stats: DatasetStats | null }) {
  const [message, setMessage] = useState<string | null>(null);

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
    <section>
      <h2 className="mb-3 text-lg font-medium">4 · Dataset</h2>
      <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
        <div className="mb-2 flex justify-between text-sm">
          <span>
            {approved} approved / {target} target ({pct}%)
          </span>
          <span className="text-neutral-400">
            {stats?.pending ?? 0} pending · {stats?.rejected ?? 0} rejected
          </span>
        </div>
        <div className="mb-4 h-2 overflow-hidden rounded bg-neutral-800">
          <div
            className="h-full bg-amber-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <button
          onClick={() => void handleExport()}
          className="rounded bg-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-600"
        >
          Export dataset (train/valid JSONL)
        </button>
        {message && <p className="mt-3 text-sm text-neutral-300">{message}</p>}
      </div>
    </section>
  );
}

/* ---------- 5. Training + models ---------- */

function TrainingSection({
  models,
  onStarted,
}: {
  models: PersonaModel[];
  onStarted: () => void;
}) {
  const [name, setName] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [testPrompt, setTestPrompt] = useState("");
  const [testModelId, setTestModelId] = useState<number | null>(null);
  const [testAnswer, setTestAnswer] = useState<string | null>(null);
  const [testBusy, setTestBusy] = useState(false);

  async function handleStart() {
    setMessage(null);
    try {
      const res = await startTraining(name || undefined);
      setMessage(`Training job #${res.job_id} started — logs in Jobs above.`);
      onStarted();
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
    <section>
      <h2 className="mb-3 text-lg font-medium">5 · Training & models</h2>
      <div className="space-y-4 rounded-lg border border-neutral-700 bg-neutral-900 p-4">
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
        {message && <p className="text-sm text-neutral-300">{message}</p>}

        <div>
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

        {ready.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-medium text-neutral-300">
              Test a model
            </h3>
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
                placeholder="Ask AI-Jonas something…"
                className="min-w-64 flex-1 rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-sm"
              />
              <button
                onClick={() => void handleTest()}
                disabled={testBusy || testModelId === null}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-500 disabled:opacity-50"
              >
                {testBusy ? "Generating… (first run loads the model)" : "Ask"}
              </button>
            </div>
            {testAnswer && (
              <p className="mt-3 whitespace-pre-wrap rounded bg-neutral-800 p-3 text-sm text-neutral-200">
                {testAnswer}
              </p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
