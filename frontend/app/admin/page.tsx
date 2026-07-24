"use client";

/**
 * Admin overview — the map of the console.
 *
 * One card per section with a plain-language description and a live
 * status line, plus a computed "suggested next step" so an admin
 * always knows where to go.
 */

import type { Route } from "next";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ActiveDeployment,
  AdminUser,
  DatasetStats,
  Job,
  PersonaModel,
  Transcript,
  getDatasetStats,
  getDeployment,
  listJobs,
  listModels,
  listTranscripts,
  listUsers,
} from "@/lib/admin";

export default function AdminOverviewPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<DatasetStats | null>(null);
  const [models, setModels] = useState<PersonaModel[]>([]);
  const [deployment, setDeployment] = useState<ActiveDeployment | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [u, t, j, s, m, d] = await Promise.all([
          listUsers(),
          listTranscripts(),
          listJobs(),
          getDatasetStats(),
          listModels(),
          getDeployment(),
        ]);
        if (cancelled) return;
        setUsers(u.users);
        setTranscripts(t.transcripts);
        setJobs(j.jobs);
        setStats(s);
        setModels(m.models);
        setDeployment(d.active);
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
  const pending = stats?.pending ?? 0;
  const approved = stats?.approved ?? 0;
  const target = stats?.target ?? 500;
  const readyModels = models.filter((m) => m.status === "ready").length;
  const admins = users.filter((u) => u.role === "admin").length;

  // The single most useful next action, so nobody has to guess.
  let nextStep: { href: Route; label: string; why: string };
  if (transcripts.length === 0) {
    nextStep = {
      href: "/admin/studio",
      label: "Upload your first transcript",
      why: "Everything starts with a lesson transcript in the Training Studio.",
    };
  } else if (activeJobs > 0) {
    nextStep = {
      href: "/admin/studio/jobs",
      label: `Watch ${activeJobs} running job${activeJobs > 1 ? "s" : ""}`,
      why: "Extraction or training is in progress — logs stream live.",
    };
  } else if (pending > 0) {
    nextStep = {
      href: "/admin/studio/review",
      label: `Review ${pending} pending pair${pending > 1 ? "s" : ""}`,
      why: "Only approved pairs make it into the training dataset.",
    };
  } else if (approved > 0 && readyModels === 0) {
    nextStep = {
      href: "/admin/studio/train",
      label: "Start a training run",
      why: `You have ${approved} approved pairs ready to train on.`,
    };
  } else if (readyModels > 0 && !deployment) {
    nextStep = {
      href: "/admin/testing",
      label: "Test your trained model",
      why: "If it sounds right, put it live from the Deployment page.",
    };
  } else if (deployment) {
    nextStep = {
      href: "/admin/deployment",
      label: `${deployment.name} is live in chat`,
      why: "Check on it, or roll back to the stock pipeline anytime.",
    };
  } else {
    nextStep = {
      href: "/admin/studio",
      label: "Upload more transcripts",
      why: "More approved pairs → better persona. Target is ~500.",
    };
  }

  const sections: {
    href: Route;
    title: string;
    what: string;
    stat: string;
    alert?: boolean;
  }[] = [
    {
      href: "/admin/users",
      title: "Users",
      what: "Registered accounts and their roles. Promote trusted people to admin or demote them back to student.",
      stat: `${users.length} user${users.length === 1 ? "" : "s"} · ${admins} admin${admins === 1 ? "" : "s"}`,
    },
    {
      href: "/admin/studio",
      title: "Training Studio",
      what: "The five-step pipeline that turns lesson transcripts into a fine-tuned persona model: upload, jobs, review, dataset, train.",
      stat:
        activeJobs > 0
          ? `${activeJobs} job${activeJobs > 1 ? "s" : ""} running`
          : pending > 0
            ? `${pending} pair${pending > 1 ? "s" : ""} to review`
            : `${approved}/${target} pairs approved`,
      alert: activeJobs > 0 || pending > 0,
    },
    {
      href: "/admin/testing",
      title: "Model Testing",
      what: "A safe playground: ask trained models questions and judge whether they sound like the teacher. Never touches live chat.",
      stat: `${readyModels} model${readyModels === 1 ? "" : "s"} ready`,
    },
    {
      href: "/admin/deployment",
      title: "Deployment",
      what: "Controls what answers live chat: the stock agent pipeline, or a trained persona model. Deploy and roll back with one click.",
      stat: deployment ? `${deployment.name} live` : "stock pipeline",
      alert: Boolean(deployment),
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

      <div className="grid gap-3 sm:grid-cols-2">
        {sections.map((section) => (
          <Link
            key={section.href}
            href={section.href}
            className="group rounded-lg border border-ink-200 bg-white p-4 shadow-sm transition-colors hover:border-saffron-400 dark:border-ink-700 dark:bg-ink-900 dark:hover:border-saffron-500"
          >
            <div className="mb-2 flex items-center gap-2">
              <span className="font-medium text-ink-900 group-hover:text-saffron-700 dark:text-ink-50 dark:group-hover:text-saffron-300">
                {section.title}
              </span>
              <span
                className={`ml-auto rounded px-2 py-0.5 text-xs ${
                  section.alert
                    ? "bg-saffron-100 font-medium text-saffron-800 dark:bg-saffron-900/40 dark:text-saffron-200"
                    : "bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-300"
                }`}
              >
                {section.stat}
              </span>
            </div>
            <p className="text-sm leading-relaxed text-ink-500 dark:text-ink-300">
              {section.what}
            </p>
          </Link>
        ))}
      </div>

      <p className="text-sm text-ink-500 dark:text-ink-400">
        The full journey: <span className="font-medium">Training Studio</span>{" "}
        builds a model from transcripts →{" "}
        <span className="font-medium">Model Testing</span> checks it sounds
        right → <span className="font-medium">Deployment</span> puts it live
        in chat.
      </p>
    </div>
  );
}
