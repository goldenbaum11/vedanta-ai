"use client";

import { AGENT_LABELS, type AgentName } from "@/lib/api";

interface AgentSelectorProps {
  value: AgentName | "auto";
  onChange: (next: AgentName | "auto") => void;
  disabled?: boolean;
}

const AGENT_ORDER: AgentName[] = [
  "vedic_scholar",
  "sanskrit_grammar",
  "communication",
  "infosec",
  "survival",
  "media",
];

export function AgentSelector({ value, onChange, disabled }: AgentSelectorProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor="agent-select" className="text-xs font-medium text-ink-500">
        Route to
      </label>
      <select
        id="agent-select"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as AgentName | "auto")}
        className="rounded-md border border-ink-200 bg-white px-2 py-1 text-sm text-ink-900 shadow-sm focus:border-saffron-500 focus:outline-none focus:ring-2 focus:ring-saffron-300 disabled:opacity-50 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-50"
      >
        <option value="auto">Auto (intent classifier)</option>
        {AGENT_ORDER.map((agent) => (
          <option key={agent} value={agent}>
            {AGENT_LABELS[agent]}
          </option>
        ))}
      </select>
    </div>
  );
}
