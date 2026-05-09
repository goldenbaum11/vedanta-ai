/**
 * Stable per-browser user identifier.
 *
 * We don't have authentication yet (Phase 4 work), but conversation
 * history needs *some* notion of "who is asking" so each browser sees
 * its own thread instead of every visitor's combined log. A random
 * value persisted to localStorage is good enough for now and is
 * forward-compatible with real auth: when JWT auth lands, the client
 * can swap this anonymous id for the authenticated subject.
 */

const STORAGE_KEY = "vedanta:userId";

function generateAnonymousId(): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36);
  return `anon_${random}`;
}

export function getOrCreateUserId(): string {
  if (typeof window === "undefined") {
    return "";
  }
  let id = window.localStorage.getItem(STORAGE_KEY);
  if (!id) {
    id = generateAnonymousId();
    window.localStorage.setItem(STORAGE_KEY, id);
  }
  return id;
}

export function clearUserId(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(STORAGE_KEY);
  }
}
