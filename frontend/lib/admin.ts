/**
 * Admin API client — persona data pipeline.
 * All calls require an admin JWT (see lib/auth.ts).
 */

import { authHeaders } from "./auth";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface Transcript {
  id: number;
  filename: string;
  uploaded_by: string | null;
  target_speaker: string;
  word_count: number;
  turn_count: number;
  pair_count: number;
  status: string;
  created_at: string;
}

export interface Job {
  id: number;
  kind: "extraction" | "training";
  status: "queued" | "running" | "succeeded" | "failed";
  transcript_id: number | null;
  model_name: string | null;
  log?: string;
  error: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface Pair {
  id: number;
  transcript_id: number;
  question: string;
  answer: string;
  kind: string;
  segment: number | null;
  status: "pending" | "approved" | "rejected";
  created_at: string;
  reviewed_at: string | null;
}

export interface DatasetStats {
  pending: number;
  approved: number;
  rejected: number;
  target: number;
}

export interface PersonaModel {
  id: number;
  name: string;
  base_model: string;
  adapter_path: string | null;
  status: "training" | "ready" | "failed";
  train_pairs: number;
  val_pairs: number;
  notes: string | null;
  created_at: string;
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* keep status code */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function uploadTranscript(
  filename: string,
  content: string,
  targetSpeaker?: string,
): Promise<{ transcript_id: number; job_id: number; speakers: string[] }> {
  return request("/api/v1/admin/transcripts", {
    method: "POST",
    body: JSON.stringify({
      filename,
      content,
      target_speaker: targetSpeaker || null,
    }),
  });
}

export function listTranscripts(): Promise<{ transcripts: Transcript[] }> {
  return request("/api/v1/admin/transcripts");
}

export function listJobs(): Promise<{ jobs: Job[] }> {
  return request("/api/v1/admin/jobs");
}

export function getJob(id: number): Promise<Job> {
  return request(`/api/v1/admin/jobs/${id}`);
}

export function listPairs(params: {
  status?: string;
  transcript_id?: number;
}): Promise<{ pairs: Pair[] }> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.transcript_id != null)
    qs.set("transcript_id", String(params.transcript_id));
  return request(`/api/v1/admin/pairs?${qs.toString()}`);
}

export function updatePair(
  id: number,
  patch: { status?: string; question?: string; answer?: string },
): Promise<Pair> {
  return request(`/api/v1/admin/pairs/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function getDatasetStats(): Promise<DatasetStats> {
  return request("/api/v1/admin/dataset/stats");
}

export function exportDataset(): Promise<{
  train: number;
  valid: number;
  dir: string;
}> {
  return request("/api/v1/admin/dataset/export", { method: "POST" });
}

export function startTraining(
  modelName?: string,
): Promise<{ job_id: number }> {
  return request("/api/v1/admin/training/start", {
    method: "POST",
    body: JSON.stringify({ model_name: modelName || null }),
  });
}

export function listModels(): Promise<{ models: PersonaModel[] }> {
  return request("/api/v1/admin/models");
}

export function testModel(
  id: number,
  prompt: string,
): Promise<{ answer: string }> {
  return request(`/api/v1/admin/models/${id}/test`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}
