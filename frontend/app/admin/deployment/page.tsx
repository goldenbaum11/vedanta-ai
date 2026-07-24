"use client";

import { PageHeader } from "@/components/admin/PageHeader";
import { DeploymentSection } from "@/components/admin/DeploymentSection";

export default function DeploymentPage() {
  return (
    <div>
      <PageHeader
        title="Deployment"
        description="Controls what answers the live chat. By default the stock pipeline runs (six specialist agents with RAG). Deploying a trained persona model substitutes it for the pipeline — every chat message is then answered by AI-Jonas. Roll back anytime; deployments are audited and history is kept."
      />
      <DeploymentSection />
    </div>
  );
}
