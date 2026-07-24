"use client";

import { PageHeader } from "@/components/admin/PageHeader";
import { UsersSection } from "@/components/admin/UsersSection";

export default function UsersPage() {
  return (
    <div>
      <PageHeader
        title="Users"
        description="Every registered account. Admins can access this console; students only use the chat. Promote a trusted account to admin or demote one that no longer needs access — you cannot change your own role, so there is always at least one admin."
      />
      <UsersSection />
    </div>
  );
}
