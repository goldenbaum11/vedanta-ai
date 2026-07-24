"use client";

import { useEffect, useRef, useState } from "react";
import { Job, getJob, listJobs } from "@/lib/admin";

const POLL_MS = 2500;

export function JobsSection() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [openJob, setOpenJob] = useState<number | null>(null);
  const [log, setLog] = useState("");
  const logRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await listJobs();
        if (!cancelled) setJobs(res.jobs);
      } catch {
        /* ignore */
      }
    }
    void load();
    const interval = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

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
    <div className="rounded-lg border border-neutral-700 bg-neutral-900">
      {jobs.length === 0 && (
        <p className="p-4 text-sm text-neutral-500">
          No jobs yet — upload a transcript to start one.
        </p>
      )}
      <ul className="divide-y divide-neutral-800">
        {jobs.map((job) => (
          <li key={job.id} className="p-3">
            <button
              onClick={() => setOpenJob(openJob === job.id ? null : job.id)}
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
                className="mt-2 max-h-72 overflow-auto rounded bg-black p-3 text-xs leading-relaxed text-green-300"
              >
                {log || "(no output yet)"}
              </pre>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
