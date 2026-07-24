"use client";

/**
 * Admin overview — the map of the persona pipeline.
 *
 * Shows what each stage does, live counts, and where to go next.
 * The actual work happens on the dedicated sub-pages.
 */

import type { Route } from "next";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  DatasetStats,
  Job,
  PersonaModel,
  Transcript,
  getDatasetStats,
  listJobs,
  listModels,
  listTranscripts,
} from "@/lib/admin";

export default function AdminOverviewPage() {
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<DatasetStats | null>(null);
  const [models, setModels] = useState<PersonaModel[]>([]);

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
    const interval = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const activeJobs = jobs.filter(
    (j) => j.status === "running" || j.status === "queued",
  ).length;
  const failedJobs = jobs.filter((j) => j.status === "failed").length;
  const pending = stats?.pending ?? 0;
  const approved = stats?.approved ?? 0;
  const target = stats?.target ?? 500;
  const readyModels = models.filter((m) => m.status === "ready").length;

  // Figure out the most useful next action so the user never has to guess.
  let nextStep: { href: Route; label: string; why: string };
  if (transcripts.length === 0) {
    nextStep = {
      href: "/admin/upload",
      label: "Upload your first transcript",
      why: "The pipeline starts with a speaker-labelled lesson transcript.",
    };
  } else if (activeJobs > 0) {
    nextStep = {
      href: "/admin/jobs",
      label: `Watch ${activeJobs} running job${activeJobs > 1 ? "s" : ""}`,
      why: "Extraction or training is in progress — logs stream live.",
    };
  } else if (pending > 0) {
    nextStep = {
      href: "/admin/review",
      label: `Review ${pending} pending pair${pending > 1 ? "s" : ""}`,
      why: "Only approved pairs make it into the training dataset.",
    };
  } else if (approved > 0 && readyModels === 0) {
    nextStep = {
      href: "/admin/training",
      label: "Start a training run",
      why: `You have ${approved} approved pairs ready to train on.`,
    };
  } else if (readyModels > 0) {
    nextStep = {
      href: "/admin/training",
      label: "Test your trained model",
      why: "Ask AI-Jonas a question and compare it to the real thing.",
    };
  } else {
    nextStep = {
      href: "/admin/upload",
      label: "Upload more transcripts",
      why: "More approved pairs → better persona. Target is ~500.",
    };
  }

  const steps: {
    href: Route;
    num: string;
    title: string;
    what: string;
    stat: string;
    alert?: boolean;
  }[] = [
    {
      href: "/admin/upload",
      num: "1",
      title: "Upload",
      what: "Drop a speaker-labelled .txt lesson transcript. Extraction (turn splitting + LLM Q&A mining) starts automatically.",
      stat: `${transcripts.length} transcript${transcripts.length === 1 ? "" : "s"}`,
    },
    {
      href: "/admin/jobs",
      num: "2",
      title: "Jobs",
      what: "Live status and streaming logs for extraction and training runs — everything the pipeline prints, as it happens.",
      stat:
        activeJobs > 0
          ? `${activeJobs} active`
          : failedJobs > 0
            ? `${failedJobs} failed`
            : `${jobs.length} total`,
      alert: activeJobs > 0 || failedJobs > 0,
    },
    {
      href: "/admin/review",
      num: "3",
      title: "Review",
      what: "Approve, reject, or edit the Q&A pairs the extractor found. This human pass is what keeps the dataset clean.",
      stat: pending > 0 ? `${pending} waiting` : "queue empty",
      alert: pending > 0,
    },
    {
      href: "/admin/dataset",
      num: "4",
      title: "Dataset",
      what: "Progress toward the training target and manual export of the train/valid JSONL files.",
      stat: `${approved} / ${target} approved`,
    },
    {
      href: "/admin/training",
      num: "5",
      title: "Training",
      what: "Fine-tune a LoRA adapter on the approved pairs, track past runs, and chat-test any ready model.",
      stat: `${readyModels} ready model${readyModels === 1 ? "" : "s"}`,
    },
  ];

  return (
    <div className="space-y-8">
      <div className="rounded-lg border border-saffron-200 bg-saffron-50 p-4 dark:border-saffron-700/50 dark:bg-saffron-900/20">
        <p className="text-xs font-semibold uppercase tracking-wide text-saffron-700 dark:text-saffron-400">
          Suggested next step
        </p>
        <Link
          href={nextStep.href}
          className="mt-1 block text-lg font-medium text-saffron-800 hover:underline dark:text-saffron-200"
        >
          {nextStep.label} →
        </Link>
        <p className="mt-1 text-sm text-ink-600 dark:text-ink-300">
          {nextStep.why}
        </p>
      </div>

      <div>
        <h2 className="mb-3 text-lg font-medium text-ink-900 dark:text-ink-50">
          How the pipeline works
        </h2>
        <p className="mb-4 text-sm text-ink-500 dark:text-ink-300">
          Each lesson transcript flows left to right through five stages. You
          only do manual work in two places: uploading (1) and reviewing (3) —
          the rest runs on its own.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {steps.map((step) => (
            <Link
              key={step.href}
              href={step.href}
              className="group rounded-lg border border-ink-200 bg-white p-4 shadow-sm transition-colors hover:border-saffron-400 dark:border-ink-700 dark:bg-ink-900 dark:hover:border-saffron-500"
            >
              <div className="mb-2 flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-saffron-100 text-xs font-semibold text-saffron-800 dark:bg-saffron-900/40 dark:text-saffron-200">
                  {step.num}
                </span>
                <span className="font-medium text-ink-900 group-hover:text-saffron-700 dark:text-ink-50 dark:group-hover:text-saffron-300">
                  {step.title}
                </span>
                <span
                  className={`ml-auto rounded px-2 py-0.5 text-xs ${
                    step.alert
                      ? "bg-saffron-100 font-medium text-saffron-800 dark:bg-saffron-900/40 dark:text-saffron-200"
                      : "bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-300"
                  }`}
                >
                  {step.stat}
                </span>
              </div>
              <p className="text-sm leading-relaxed text-ink-500 dark:text-ink-300">
                {step.what}
              </p>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
