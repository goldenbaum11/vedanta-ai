"use client";

/**
 * Admin section layout: auth gate + tab navigation.
 *
 * Each pipeline step is its own page:
 *   /admin           — overview of the whole pipeline
 *   /admin/upload    — add transcripts
 *   /admin/jobs      — watch extraction/training logs
 *   /admin/review    — approve/reject/edit pairs
 *   /admin/dataset   — progress + export
 *   /admin/training  — train + test models
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getAuthProfile, onAuthChange } from "@/lib/auth";

const TABS = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/upload", label: "1 · Upload" },
  { href: "/admin/jobs", label: "2 · Jobs" },
  { href: "/admin/review", label: "3 · Review" },
  { href: "/admin/dataset", label: "4 · Dataset" },
  { href: "/admin/training", label: "5 · Training" },
] as const;

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [role, setRole] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setRole(getAuthProfile()?.role ?? null);
    setHydrated(true);
    return onAuthChange((auth) => setRole(auth?.profile.role ?? null));
  }, []);

  return (
    <div className="py-2">
      <div className="mb-1 flex items-baseline justify-between">
        <h1 className="font-serif text-2xl font-semibold text-ink-900 dark:text-ink-50">
          Persona pipeline
        </h1>
        <Link
          href="/"
          className="text-sm text-ink-500 hover:text-ink-900 dark:text-ink-300 dark:hover:text-white"
        >
          ← Back to chat
        </Link>
      </div>
      <p className="mb-6 text-sm text-ink-500 dark:text-ink-300">
        Transcripts → extraction → review → dataset → LoRA training
      </p>

      {!hydrated ? null : role !== "admin" ? (
        <div className="rounded-lg border border-ink-200 bg-white p-4 text-sm dark:border-ink-700 dark:bg-ink-900">
          {role === null ? (
            <p className="text-ink-700 dark:text-ink-200">
              Sign in with an admin account on the{" "}
              <Link
                href="/"
                className="text-saffron-700 underline dark:text-saffron-300"
              >
                main chat page
              </Link>
              , then come back here.
            </p>
          ) : (
            <p className="text-red-700 dark:text-red-400">
              Your account does not have the admin role. Promote it with{" "}
              <code className="text-ink-700 dark:text-ink-200">
                python3 scripts/make_admin.py --email you@example.com
              </code>{" "}
              and sign in again.
            </p>
          )}
        </div>
      ) : (
        <>
          <nav className="mb-8 flex flex-wrap gap-1 border-b border-ink-200 pb-2 text-sm dark:border-ink-800">
            {TABS.map((tab) => {
              const active =
                tab.href === "/admin"
                  ? pathname === "/admin"
                  : pathname.startsWith(tab.href);
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  className={`rounded-md px-3 py-1.5 transition ${
                    active
                      ? "bg-saffron-600 text-white shadow-sm"
                      : "text-ink-500 hover:bg-ink-100 hover:text-ink-900 dark:text-ink-300 dark:hover:bg-ink-800 dark:hover:text-white"
                  }`}
                >
                  {tab.label}
                </Link>
              );
            })}
          </nav>
          {children}
        </>
      )}
    </div>
  );
}
