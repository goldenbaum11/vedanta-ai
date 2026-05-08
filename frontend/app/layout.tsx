import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vedanta AI",
  description:
    "Local-first multi-agent AI for an ashram community: sacred texts, communication, security, survival, and media.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="flex min-h-screen flex-col">
          <header className="border-b border-ink-200/70 bg-white/70 backdrop-blur dark:border-ink-800 dark:bg-ink-950/70">
            <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
              <Link
                href="/"
                className="flex items-center gap-2 font-serif text-xl font-semibold text-saffron-700 dark:text-saffron-300"
              >
                <span aria-hidden className="text-2xl">
                  ॐ
                </span>
                Vedanta AI
              </Link>
              <nav className="flex items-center gap-4 text-sm">
                <Link
                  href="/"
                  className="text-ink-600 hover:text-ink-900 dark:text-ink-300 dark:hover:text-white"
                >
                  Chat
                </Link>
                <Link
                  href="/dashboard"
                  className="text-ink-600 hover:text-ink-900 dark:text-ink-300 dark:hover:text-white"
                >
                  Dashboard
                </Link>
              </nav>
            </div>
          </header>
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
            {children}
          </main>
          <footer className="border-t border-ink-200/70 py-3 text-center text-xs text-ink-500 dark:border-ink-800 dark:text-ink-400">
            Local-first. No data leaves this machine. Phase 1 — Foundation.
          </footer>
        </div>
      </body>
    </html>
  );
}
