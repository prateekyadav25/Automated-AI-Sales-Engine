import type { ReactNode } from "react";

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="panel p-8">
      <div className="h-3 w-40 animate-pulse rounded bg-azure-100" />
      <div className="mt-4 h-24 animate-pulse rounded-lg bg-white/60" />
      <p className="mt-4 text-sm text-[var(--muted)]">{label}…</p>
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="panel px-8 py-14 text-center">
      <p className="text-lg font-semibold text-navy">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--muted)]">{body}</p>
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{message}</div>;
}

export function DeniedState() {
  return <ErrorState message="You do not have permission to view this page." />;
}
