"use client";

import { PageHeader } from "@/components/admin/PageHeader";
import { UploadSection } from "@/components/admin/UploadSection";

export default function StudioUploadPage() {
  return (
    <div>
      <PageHeader
        title="1 · Upload transcript"
        description="Start here. Drop a speaker-labelled .txt lesson transcript (the format Whisper or a human transcriber produces, with names before each turn). Extraction begins immediately: the pipeline splits the text into speaker turns, then a local LLM mines question–answer pairs from the target speaker's parts. Results land in Review."
      />
      <UploadSection />
    </div>
  );
}
