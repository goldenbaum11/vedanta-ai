"use client";

import { useCallback, useEffect, useState } from "react";

import { loginUser, registerUser } from "@/lib/api";
import {
  type AuthProfile,
  clearStoredAuth,
  getStoredAuth,
  onAuthChange,
  setStoredAuth,
} from "@/lib/auth";

type Mode = "login" | "register";

interface Props {
  /**
   * Called whenever the authenticated profile changes (sign-in,
   * sign-out, page mount). The chat view uses this to scope the
   * server-side history fetch by `user:N` once a user signs in.
   */
  onAuthStateChange?: (profile: AuthProfile | null) => void;
}

export function AuthBar({ onAuthStateChange }: Props) {
  const [profile, setProfile] = useState<AuthProfile | null>(null);
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const initial = getStoredAuth();
    setProfile(initial?.profile ?? null);
    onAuthStateChange?.(initial?.profile ?? null);
    const unsub = onAuthChange((next) => {
      setProfile(next?.profile ?? null);
      onAuthStateChange?.(next?.profile ?? null);
    });
    return () => {
      unsub();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      if (!email.trim() || !password) return;
      setBusy(true);
      setError(null);
      try {
        const fn = mode === "register" ? registerUser : loginUser;
        const result = await fn(email.trim(), password);
        setStoredAuth(result.access_token, result.user);
        setEmail("");
        setPassword("");
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Authentication failed.",
        );
      } finally {
        setBusy(false);
      }
    },
    [email, mode, password],
  );

  const signOut = useCallback(() => {
    clearStoredAuth();
  }, []);

  if (profile) {
    return (
      <div className="flex items-center gap-2 text-xs text-ink-600 dark:text-ink-300">
        <span className="rounded-full bg-saffron-100 px-2 py-0.5 font-semibold text-saffron-800 dark:bg-saffron-900/40 dark:text-saffron-200">
          {profile.email}
        </span>
        <button
          type="button"
          onClick={signOut}
          className="rounded-md border border-ink-200 px-2 py-1 transition hover:bg-ink-50 dark:border-ink-700 dark:hover:bg-ink-800"
        >
          Sign out
        </button>
      </div>
    );
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-wrap items-center gap-2 text-xs"
      aria-label={mode === "register" ? "Register" : "Sign in"}
    >
      <select
        value={mode}
        onChange={(event) => setMode(event.target.value as Mode)}
        disabled={busy}
        className="rounded-md border border-ink-200 bg-white px-2 py-1 dark:border-ink-700 dark:bg-ink-900"
      >
        <option value="login">Sign in</option>
        <option value="register">Register</option>
      </select>
      <input
        type="email"
        autoComplete="email"
        placeholder="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        disabled={busy}
        className="w-44 rounded-md border border-ink-200 bg-white px-2 py-1 dark:border-ink-700 dark:bg-ink-900"
      />
      <input
        type="password"
        autoComplete={mode === "register" ? "new-password" : "current-password"}
        placeholder="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        disabled={busy}
        minLength={mode === "register" ? 8 : 1}
        className="w-32 rounded-md border border-ink-200 bg-white px-2 py-1 dark:border-ink-700 dark:bg-ink-900"
      />
      <button
        type="submit"
        disabled={busy || !email.trim() || password.length < (mode === "register" ? 8 : 1)}
        className="rounded-md bg-saffron-600 px-3 py-1 font-medium text-white shadow-sm transition hover:bg-saffron-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? "…" : mode === "register" ? "Create" : "Sign in"}
      </button>
      {error ? (
        <span className="text-red-600 dark:text-red-400" title={error}>
          {error.length > 60 ? `${error.slice(0, 60)}…` : error}
        </span>
      ) : null}
    </form>
  );
}
