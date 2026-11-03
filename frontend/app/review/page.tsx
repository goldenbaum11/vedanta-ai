"use client";

import { ReviewSection } from "@/components/admin/ReviewSection";

export default function ReviewPage() {
  return (
    <div>
      <p className="mb-6 text-sm text-ink-500 dark:text-ink-300">
        For each pair: read the question and answer, then mark Approve,
        Reject, or Edit. Nothing is used for training until it&apos;s
        approved here.
      </p>
      <ReviewSection />
    </div>
  );
}
