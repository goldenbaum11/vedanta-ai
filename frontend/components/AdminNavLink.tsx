"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getAuthProfile, onAuthChange } from "@/lib/auth";

/**
 * "Admin" link for the site header. Rendered only when the signed-in
 * user has the admin role, so students never see it.
 */
export function AdminNavLink() {
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    setIsAdmin(getAuthProfile()?.role === "admin");
    return onAuthChange((auth) => setIsAdmin(auth?.profile.role === "admin"));
  }, []);

  if (!isAdmin) return null;
  return (
    <Link
      href="/admin"
      className="text-ink-600 hover:text-ink-900 dark:text-ink-300 dark:hover:text-white"
    >
      Admin
    </Link>
  );
}
