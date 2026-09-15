"use client";

import { Button } from "@/components/ui";

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center px-6 text-center">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-brand">Desk error</p>
      <h1 className="mt-3 text-2xl font-semibold text-navy">This screen could not be rendered</h1>
      <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
        {error.message || "An unexpected error stopped this page."}
      </p>
      <Button className="mt-6" onClick={() => reset()}>
        Try again
      </Button>
    </div>
  );
}
