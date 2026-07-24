"use client";

import { PageHeader } from "@/components/admin/PageHeader";
import { TestingSection } from "@/components/admin/TestingSection";

export default function TestingPage() {
  return (
    <div>
      <PageHeader
        title="Model Testing"
        description="A playground for trained persona models — nothing here touches live chat. Pick a model, ask it the kinds of questions students ask, and judge whether it sounds like the teacher. Recent answers stay on the page so you can compare models side by side before deploying one."
      />
      <TestingSection />
    </div>
  );
}
