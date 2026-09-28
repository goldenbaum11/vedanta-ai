"use client";

import { PageHeader } from "@/components/admin/PageHeader";
import { TrainingSection } from "@/components/admin/TrainingSection";

export default function StudioTrainPage() {
  return (
    <div>
      <PageHeader
        title="5 · Train"
        description="Fine-tunes a LoRA adapter on the approved dataset using Unsloth on this machine's GPU (the base model itself is untouched — the adapter is a small style layer on top). Each run becomes a named model in the registry below. When one is ready, try it in Model Testing, then put it live from Deployment."
      />
      <TrainingSection />
    </div>
  );
}
