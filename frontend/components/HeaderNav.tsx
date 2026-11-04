"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AdminNavLink } from "@/components/AdminNavLink";

/**
 * On /review, external reviewers only need the reviewer page itself —
 * the main chat link is hidden there to keep the page self-contained
 * for a shared link (see app/review/layout.tsx).
 */
export function HeaderNav() {
  const pathname = usePathname();
  const onReviewPage = pathname?.startsWith("/review") ?? false;

  return (
    <nav className="flex items-center gap-4 text-sm">
      {onReviewPage ? null : (
        <Link
          href="/"
          className="text-ink-600 hover:text-ink-900 dark:text-ink-300 dark:hover:text-white"
        >
          Chat
        </Link>
      )}
      <Link
        href="/dashboard"
        className="text-ink-600 hover:text-ink-900 dark:text-ink-300 dark:hover:text-white"
      >
        Dashboard
      </Link>
      <AdminNavLink />
    </nav>
  );
}
