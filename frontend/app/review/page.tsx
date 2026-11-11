"use client";

import { ReviewSection } from "@/components/admin/ReviewSection";
import { reviewStrings, useReviewLang } from "@/lib/reviewI18n";

export default function ReviewPage() {
  const [lang] = useReviewLang();
  return (
    <div>
      <p className="mb-6 text-sm text-ink-500 dark:text-ink-300">
        {reviewStrings[lang].intro}
      </p>
      <ReviewSection lang={lang} />
    </div>
  );
}
