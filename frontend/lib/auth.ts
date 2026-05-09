/**
 * Browser-side auth state.
 *
 * Stores the JWT and the latest known profile in `localStorage` so a
 * page reload doesn't bump the user out. The token is purely opaque to
 * the frontend — only the backend validates it. We do NOT decode it
 * client-side; the profile cache is populated from `/api/v1/auth/me`.
 *
 * Listeners can subscribe to changes via `onAuthChange` so multiple
 * components stay in sync without prop-drilling. (This avoids pulling
 * in a state library for a single piece of global state.)
 */

export interface AuthProfile {
  id: number;
  email: string;
  role: string;
}

interface StoredAuth {
  token: string;
  profile: AuthProfile;
}

const STORAGE_KEY = "vedanta:auth";
type Listener = (auth: StoredAuth | null) => void;
const listeners = new Set<Listener>();

function read(): StoredAuth | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as StoredAuth;
    if (!parsed?.token || !parsed?.profile?.id) return null;
    return parsed;
  } catch {
    return null;
  }
}

function write(value: StoredAuth | null): void {
  if (typeof window === "undefined") return;
  if (value === null) {
    window.localStorage.removeItem(STORAGE_KEY);
  } else {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  }
  for (const cb of listeners) cb(value);
}

export function getStoredAuth(): StoredAuth | null {
  return read();
}

export function getAuthToken(): string | null {
  return read()?.token ?? null;
}

export function getAuthProfile(): AuthProfile | null {
  return read()?.profile ?? null;
}

export function setStoredAuth(token: string, profile: AuthProfile): void {
  write({ token, profile });
}

export function clearStoredAuth(): void {
  write(null);
}

export function onAuthChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Returns headers to merge into authenticated requests. */
export function authHeaders(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
