"use client";

import { PageHeader } from "@/components/page-header";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div>
      <PageHeader eyebrow="Recovery" title="This desk view crashed" subtitle="The last render failed. Your session is still signed in." />
      <ErrorState message={error.message || "An unexpected error stopped this page."} />
      <Button className="mt-4" onClick={() => reset()}>
        Reload this view
      </Button>
    </div>
  );
}
