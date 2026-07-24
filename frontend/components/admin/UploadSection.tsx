"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Transcript, listTranscripts, uploadTranscript } from "@/lib/admin";

export function UploadSection() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [lastJobId, setLastJobId] = useState<number | null>(null);
  const [speaker, setSpeaker] = useState("");
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const res = await listTranscripts();
      setTranscripts(res.transcripts);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setMessage(null);
    setLastJobId(null);
    try {
      for (const file of Array.from(files)) {
        const content = await file.text();
        const res = await uploadTranscript(
          file.name,
          content,
          speaker || undefined,
        );
        setMessage(
          `Uploaded ${file.name} — extraction job #${res.job_id} started. ` +
            `Speakers found: ${res.speakers.join(", ")}.`,
        );
        setLastJobId(res.job_id);
      }
      await load();
    } catch (err) {
      setMessage(`Upload failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const statusColor = (status: string) =>
    ({
      uploaded: "text-neutral-400",
      extracting: "text-blue-400",
      review: "text-amber-400",
      failed: "text-red-400",
    })[status] ?? "text-neutral-400";

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".txt"
            multiple
            disabled={busy}
            onChange={(e) => void handleFiles(e.target.files)}
            className="text-sm file:mr-3 file:rounded file:border-0 file:bg-amber-600 file:px-3 file:py-1.5 file:text-sm file:text-white hover:file:bg-amber-500"
          />
          <input
            type="text"
            value={speaker}
            onChange={(e) => setSpeaker(e.target.value)}
            placeholder="Speaker label (default: Jonas M)"
            className="rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-sm"
          />
          {busy && <span className="text-sm text-neutral-400">Uploading…</span>}
        </div>
        {message && (
          <p className="mt-3 text-sm text-neutral-300">
            {message}{" "}
            {lastJobId !== null && (
              <Link
                href="/admin/jobs"
                className="text-amber-400 underline"
              >
                Watch it in Jobs →
              </Link>
            )}
          </p>
        )}
      </div>

      <div>
        <h3 className="mb-2 text-sm font-medium text-neutral-300">
          Uploaded transcripts
        </h3>
        <div className="overflow-hidden rounded-lg border border-neutral-700 bg-neutral-900">
          {transcripts.length === 0 ? (
            <p className="p-4 text-sm text-neutral-500">
              Nothing uploaded yet.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-800 text-left text-xs text-neutral-500">
                  <th className="px-3 py-2">File</th>
                  <th className="px-3 py-2">Words</th>
                  <th className="px-3 py-2">Turns</th>
                  <th className="px-3 py-2">Pairs</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {transcripts.map((t) => (
                  <tr key={t.id} className="border-b border-neutral-800/50">
                    <td className="px-3 py-2 font-medium">{t.filename}</td>
                    <td className="px-3 py-2">{t.word_count.toLocaleString()}</td>
                    <td className="px-3 py-2">{t.turn_count}</td>
                    <td className="px-3 py-2">{t.pair_count}</td>
                    <td className={`px-3 py-2 ${statusColor(t.status)}`}>
                      {t.status}
                    </td>
                    <td className="px-3 py-2 text-xs text-neutral-500">
                      {new Date(t.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
