"use client";

import { useState } from "react";

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
          <CitationRow key={c.id ?? idx} citation={c} index={idx + 1} />
        ))}
      </ul>
    </aside>
  );
}

function CitationRow({
  citation,
  index,
}: {
  citation: Citation;
  index: number;
}) {
  const [expanded, setExpanded] = useState(false);

  const headerSegments: string[] = [];
  if (citation.source) headerSegments.push(citation.source);
  if (citation.chapter) headerSegments.push(`ch. ${citation.chapter}`);
  if (citation.verse) headerSegments.push(`v. ${citation.verse}`);
  if (citation.commentary_author)
    headerSegments.push(citation.commentary_author);
  if (citation.tradition) headerSegments.push(citation.tradition);
  const header =
    headerSegments.length > 0 ? headerSegments.join(" · ") : "Unknown source";

  const fullText = citation.full_text ?? "";
  const snippet = citation.snippet ?? "";
  const hasMoreThanSnippet =
    fullText.length > 0 && fullText.length > snippet.length;

  return (
    <li className="leading-snug">
      <div className="flex items-baseline gap-2">
        <span className="rounded bg-saffron-200 px-1.5 py-0.5 font-mono text-xs font-semibold text-saffron-900 dark:bg-saffron-800/60 dark:text-saffron-100">
          [{index}]
        </span>
        <span className="font-medium">{header}</span>
      </div>

      {expanded && fullText ? (
        <pre className="mt-1 whitespace-pre-wrap break-words font-sans text-ink-700 dark:text-ink-200">
          {fullText}
        </pre>
      ) : snippet ? (
        <div className="mt-1 line-clamp-3 text-ink-600 dark:text-ink-300">
          {snippet}
          {hasMoreThanSnippet ? "…" : null}
        </div>
      ) : null}

      <div className="mt-1 flex items-center gap-3 text-xs">
        {hasMoreThanSnippet ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="rounded px-1.5 py-0.5 font-medium text-saffron-700 hover:bg-saffron-100 dark:text-saffron-300 dark:hover:bg-saffron-900/40"
            aria-expanded={expanded}
          >
            {expanded ? "Show less" : "Show full chunk"}
          </button>
        ) : null}
        {typeof citation.distance === "number" ? (
          <span className="text-ink-500 dark:text-ink-400">
            distance {citation.distance.toFixed(3)}
          </span>
        ) : null}
        {citation.id ? (
          <span className="font-mono text-ink-400 dark:text-ink-500">
            {citation.id}
          </span>
        ) : null}
      </div>
    </li>
  );
}
