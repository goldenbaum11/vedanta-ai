"use client";

import { PageHeader } from "@/components/admin/PageHeader";
import { ReviewSection } from "@/components/admin/ReviewSection";

export default function ReviewPage() {
  return (
    <div>
      <PageHeader
        title="3 · Review pairs"
        description="The human quality gate. The extractor is good but not perfect — approve pairs that sound like the teacher, reject noise, and edit anything worth keeping but slightly off (typos, leftover names, trailing fragments). Only approved pairs enter the training dataset, so this pass directly decides how good the persona gets."
      />
      <ReviewSection />
    </div>
  );
}
