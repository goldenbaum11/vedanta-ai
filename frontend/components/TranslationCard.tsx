"use client";

import type { Citation } from "@/lib/api";

interface TranslationCardProps {
  citations: Citation[];
}

export function TranslationCard({ citations }: TranslationCardProps) {
  if (citations.length === 0) {
    return null;
  }
  return (
    <aside className="mt-3 rounded-md border border-saffron-200 bg-saffron-50 p-3 text-sm text-ink-800 dark:border-saffron-700/60 dark:bg-saffron-900/20 dark:text-ink-100">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-saffron-700 dark:text-saffron-300">
        Sources
      </div>
      <ul className="space-y-2">
        {citations.map((c, idx) => (
          <li key={c.id ?? idx} className="leading-snug">
            <div className="font-medium">
              {c.source ?? "Unknown source"}
              {c.chapter ? ` · ch. ${c.chapter}` : ""}
              {c.verse ? ` · v. ${c.verse}` : ""}
              {c.commentary_author ? ` · ${c.commentary_author}` : ""}
              {c.tradition ? ` · ${c.tradition}` : ""}
            </div>
            {c.snippet ? (
              <div className="mt-1 text-ink-600 dark:text-ink-300">{c.snippet}</div>
            ) : null}
            {typeof c.distance === "number" ? (
              <div className="mt-1 text-xs text-ink-500 dark:text-ink-400">
                relevance distance: {c.distance.toFixed(3)}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </aside>
  );
}
