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
    <main className="mx-auto max-w-5xl px-4 py-8 text-neutral-100">
      <div className="mb-1 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Persona pipeline</h1>
        <Link
          href="/"
          className="text-sm text-neutral-400 hover:text-neutral-200"
        >
          ← Back to chat
        </Link>
      </div>
      <p className="mb-6 text-sm text-neutral-400">
        Transcripts → extraction → review → dataset → LoRA training
      </p>

      {!hydrated ? null : role !== "admin" ? (
        <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4 text-sm">
          {role === null ? (
            <p className="text-neutral-300">
              Sign in with an admin account on the{" "}
              <Link href="/" className="text-amber-400 underline">
                main chat page
              </Link>
              , then come back here.
            </p>
          ) : (
            <p className="text-red-400">
              Your account does not have the admin role. Promote it with{" "}
              <code className="text-neutral-300">
                python3 scripts/make_admin.py --email you@example.com
              </code>{" "}
              and sign in again.
            </p>
          )}
        </div>
      ) : (
        <>
          <nav className="mb-8 flex flex-wrap gap-1 border-b border-neutral-800 pb-2 text-sm">
            {TABS.map((tab) => {
              const active =
                tab.href === "/admin"
                  ? pathname === "/admin"
                  : pathname.startsWith(tab.href);
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  className={`rounded-t px-3 py-1.5 ${
                    active
                      ? "bg-amber-600 text-white"
                      : "text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200"
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
    </main>
  );
}
