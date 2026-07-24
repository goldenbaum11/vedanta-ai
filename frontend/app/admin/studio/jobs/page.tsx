"use client";

import { PageHeader } from "@/components/admin/PageHeader";
import { JobsSection } from "@/components/admin/JobsSection";

export default function StudioJobsPage() {
  return (
    <div>
      <PageHeader
        title="2 · Jobs"
        description="Everything the pipeline runs in the background — extraction after an upload, LoRA training after you press Start. Click a job to stream its live log output; failed jobs show the error inline. This page updates automatically every few seconds."
      />
      <JobsSection />
    </div>
  );
}
