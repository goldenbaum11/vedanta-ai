"use client";

/**
 * Standalone pairs-review page for external collaborators.
 *
 * Deliberately separate from /admin — a `reviewer`-role account can reach
 * only this page and the pairs API it calls. No link here ever points at
 * /admin/studio/train, /admin/users, or /admin/deployment; those stay
 * admin-only. Embeds its own sign-in (AuthBar) so a shared link works
 * standalone, without detouring through the main chat page first.
 */

import { useEffect, useState } from "react";
import { AuthBar } from "@/components/AuthBar";
import { getAuthProfile, onAuthChange } from "@/lib/auth";
import { reviewStrings, useReviewLang } from "@/lib/reviewI18n";

export default function ReviewLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [role, setRole] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [lang, setLang] = useReviewLang();
  const t = reviewStrings[lang];

  useEffect(() => {
    setRole(getAuthProfile()?.role ?? null);
    setHydrated(true);
    return onAuthChange((auth) => setRole(auth?.profile.role ?? null));
  }, []);

  const allowed = role === "admin" || role === "reviewer";

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-serif text-2xl font-semibold text-ink-900 dark:text-ink-50">
          {t.title}
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setLang(lang === "en" ? "pt" : "en")}
            aria-label={t.switchLabel}
            title={t.switchLabel}
            className="rounded-md border border-ink-200 px-2 py-1 text-xs font-medium text-ink-700 transition hover:bg-ink-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
          >
            {lang === "en" ? "🇧🇷 " : "🇬🇧 "}
            {t.switchTo}
          </button>
          <AuthBar hideRegister labels={t.auth} />
        </div>
      </div>

      {!hydrated ? null : !allowed ? (
        <div className="rounded-lg border border-ink-200 bg-white p-4 text-sm dark:border-ink-700 dark:bg-ink-900">
          {role === null ? (
            <p className="text-ink-700 dark:text-ink-200">{t.signInPrompt}</p>
          ) : (
            <p className="text-red-700 dark:text-red-400">{t.noAccess}</p>
          )}
        </div>
      ) : (
        children
      )}
    </div>
  );
}
