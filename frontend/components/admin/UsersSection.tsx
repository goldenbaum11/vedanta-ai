"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminUser, listUsers, updateUserRole } from "@/lib/admin";
import { getAuthProfile } from "@/lib/auth";

export function UsersSection() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [selfEmail, setSelfEmail] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await listUsers();
      setUsers(res.users);
    } catch (err) {
      setMessage(`Could not load users: ${(err as Error).message}`);
    }
  }, []);

  useEffect(() => {
    setSelfEmail(getAuthProfile()?.email ?? null);
    void load();
  }, [load]);

  async function setRole(user: AdminUser, role: "student" | "admin") {
    setBusyId(user.id);
    setMessage(null);
    try {
      await updateUserRole(user.id, role);
      setMessage(`${user.email} is now ${role}.`);
      await load();
    } catch (err) {
      setMessage(`Failed: ${(err as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      {message && (
        <p className="mb-3 text-sm text-ink-700 dark:text-ink-200">{message}</p>
      )}
      <div className="overflow-hidden rounded-lg border border-ink-200 bg-white shadow-sm dark:border-ink-700 dark:bg-ink-900">
        {users.length === 0 ? (
          <p className="p-4 text-sm text-ink-500 dark:text-ink-400">
            No users yet.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-left text-xs text-ink-500 dark:border-ink-800 dark:text-ink-400">
                <th className="px-3 py-2">Email</th>
                <th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Registered</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const isSelf = user.email === selfEmail;
                return (
                  <tr
                    key={user.id}
                    className="border-b border-ink-100 dark:border-ink-800/50"
                  >
                    <td className="px-3 py-2 font-medium">
                      {user.email}
                      {isSelf && (
                        <span className="ml-2 text-xs text-ink-400">(you)</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded px-2 py-0.5 text-xs ${
                          user.role === "admin"
                            ? "bg-saffron-100 font-medium text-saffron-800 dark:bg-saffron-900/40 dark:text-saffron-200"
                            : "bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300"
                        }`}
                      >
                        {user.role}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-ink-500 dark:text-ink-400">
                      {new Date(user.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-2">
                      {isSelf ? (
                        <span className="text-xs text-ink-400">
                          own role locked
                        </span>
                      ) : user.role === "admin" ? (
                        <button
                          disabled={busyId === user.id}
                          onClick={() => void setRole(user, "student")}
                          className="rounded-md bg-ink-100 px-2 py-1 text-xs hover:bg-ink-200 disabled:opacity-50 dark:bg-ink-700 dark:hover:bg-ink-600"
                        >
                          Demote to student
                        </button>
                      ) : (
                        <button
                          disabled={busyId === user.id}
                          onClick={() => void setRole(user, "admin")}
                          className="rounded-md bg-saffron-600 px-2 py-1 text-xs text-white hover:bg-saffron-700 disabled:opacity-50"
                        >
                          Make admin
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
