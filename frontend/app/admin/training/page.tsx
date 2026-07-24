"use client";

import { PageHeader } from "@/components/admin/PageHeader";
import { TrainingSection } from "@/components/admin/TrainingSection";

export default function TrainingPage() {
  return (
    <div>
      <PageHeader
        title="5 · Training & models"
        description="Fine-tunes a LoRA adapter on the approved dataset using MLX on this machine (the base model itself is untouched — the adapter is a small style layer on top). Each run becomes a named model below; when one is ready, test it right here by asking it questions."
      />
      <TrainingSection />
    </div>
  );
}
