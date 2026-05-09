import { fetchHealth, fetchMessages, AGENT_LABELS } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const [healthResult, messagesResult] = await Promise.allSettled([
    fetchHealth(),
    fetchMessages(20),
  ]);

  const health = healthResult.status === "fulfilled" ? healthResult.value : null;
  const messages =
    messagesResult.status === "fulfilled" ? messagesResult.value.messages : [];
  const error =
    healthResult.status === "rejected"
      ? healthResult.reason instanceof Error
        ? healthResult.reason.message
        : "Backend unreachable."
      : null;

  return (
    <section className="space-y-6">
      <header>
        <h1 className="font-serif text-2xl font-semibold">Admin dashboard</h1>
        <p className="text-sm text-ink-500">
          Phase 1 view: health probes and the most recent message exchanges.
          Authentication and per-user controls land in Phase 4.
        </p>
      </header>

      {error ? (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-700/70 dark:bg-red-900/30 dark:text-red-200">
          {error}
        </div>
      ) : null}

      {health ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <HealthTile
            label={`LLM (${health.dependencies.llm.provider})`}
            ok={health.dependencies.llm.reachable}
            detail={`${health.dependencies.llm.default_model} @ ${health.dependencies.llm.base_url}`}
          />
          <HealthTile
            label="ChromaDB"
            ok={health.dependencies.chroma.reachable}
            detail="vector store"
          />
          <HealthTile
            label="Database"
            ok
            detail={health.dependencies.database.path}
          />
        </div>
      ) : null}

      <div>
        <h2 className="mb-2 font-serif text-lg font-semibold">Recent messages</h2>
        {messages.length === 0 ? (
          <p className="text-sm text-ink-500">No messages yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-ink-200 bg-white shadow-sm dark:border-ink-800 dark:bg-ink-900">
            <table className="min-w-full text-sm">
              <thead className="bg-ink-100/70 text-left text-xs uppercase tracking-wide text-ink-500 dark:bg-ink-800/70 dark:text-ink-300">
                <tr>
                  <th className="px-3 py-2">Time</th>
                  <th className="px-3 py-2">Agent</th>
                  <th className="px-3 py-2">Confidence</th>
                  <th className="px-3 py-2">Query</th>
                  <th className="px-3 py-2">Response</th>
                </tr>
              </thead>
              <tbody>
                {messages.map((row) => (
                  <tr
                    key={row.id}
                    className="border-t border-ink-200 align-top dark:border-ink-800"
                  >
                    <td className="px-3 py-2 text-xs text-ink-500">
                      {new Date(row.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 font-medium">
                      {AGENT_LABELS[row.agent] ?? row.agent}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {(row.intent_confidence * 100).toFixed(0)}%
                    </td>
                    <td className="px-3 py-2">{row.query}</td>
                    <td className="px-3 py-2 text-ink-700 dark:text-ink-300">
                      {row.response}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function HealthTile({
  label,
  ok,
  detail,
}: {
  label: string;
  ok: boolean;
  detail: string;
}) {
  return (
    <div className="rounded-md border border-ink-200 bg-white p-3 shadow-sm dark:border-ink-800 dark:bg-ink-900">
      <div className="flex items-center justify-between">
        <span className="font-medium">{label}</span>
        <span
          className={
            ok
              ? "rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200"
              : "rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800 dark:bg-red-900/40 dark:text-red-200"
          }
        >
          {ok ? "ok" : "down"}
        </span>
      </div>
      <p className="mt-1 break-all text-xs text-ink-500">{detail}</p>
    </div>
  );
}
