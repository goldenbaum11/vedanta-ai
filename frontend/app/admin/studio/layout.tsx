"use client";

/**
 * Training Studio sub-layout: the five pipeline steps as tabs.
 *
 *   /admin/studio          — 1 Upload (entry point)
 *   /admin/studio/jobs     — 2 Jobs (live logs)
 *   /admin/studio/review   — 3 Review (approve/reject pairs)
 *   /admin/studio/dataset  — 4 Dataset (progress + export)
 *   /admin/studio/train    — 5 Train (LoRA runs + model registry)
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

const STEPS = [
  { href: "/admin/studio", label: "1 · Upload" },
  { href: "/admin/studio/jobs", label: "2 · Jobs" },
  { href: "/admin/studio/review", label: "3 · Review" },
  { href: "/admin/studio/dataset", label: "4 · Dataset" },
  { href: "/admin/studio/train", label: "5 · Train" },
] as const;

export default function StudioLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  return (
    <div>
      <div className="mb-6">
        <h2 className="text-lg font-medium text-ink-900 dark:text-ink-50">
          Training Studio
        </h2>
        <p className="mt-1 text-sm text-ink-500 dark:text-ink-300">
          Turns lesson transcripts into a fine-tuned persona model, in five
          steps. Work left to right; you only act in Upload, Review, and
          Train — the rest is automatic.
        </p>
      </div>
      <nav className="mb-6 flex flex-wrap gap-1 text-sm">
        {STEPS.map((step) => {
          const active =
            step.href === "/admin/studio"
              ? pathname === "/admin/studio"
              : pathname.startsWith(step.href);
          return (
            <Link
              key={step.href}
              href={step.href}
              className={`rounded-md px-3 py-1.5 transition ${
                active
                  ? "bg-ink-800 text-white dark:bg-ink-100 dark:text-ink-900"
                  : "bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-ink-800 dark:text-ink-200 dark:hover:bg-ink-700"
              }`}
            >
              {step.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
