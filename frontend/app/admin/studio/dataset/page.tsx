"use client";

import { PageHeader } from "@/components/admin/PageHeader";
import { DatasetSection } from "@/components/admin/DatasetSection";

export default function StudioDatasetPage() {
  return (
    <div>
      <PageHeader
        title="4 · Dataset"
        description="Tracks how many approved pairs you have against the training target (~500 gives a solid persona; useful results start around 100–150). Every approved pair is formatted as a chat example with the persona system prompt and split 90/10 into train/valid files for MLX."
      />
      <DatasetSection />
    </div>
  );
}
