"use client";

import { cn } from "@/lib/cn";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "line" }) {
  const styles = {
    primary: "bg-brand text-white hover:bg-brand-600",
    ghost: "bg-transparent text-ink hover:bg-azure-50/80",
    line: "border border-[var(--line-strong)] bg-white/80 text-ink hover:border-azure-600/40 hover:text-azure-700",
  }[variant];
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-[13px] font-semibold transition disabled:opacity-40",
        styles,
        className,
      )}
      {...props}
    />
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-[var(--muted)]">{label}</span>
      {children}
    </label>
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "w-full rounded-lg border border-[var(--line)] bg-white/90 px-3 py-2.5 text-sm text-ink outline-none placeholder:text-[var(--muted)] focus:border-azure-600 focus:ring-2 focus:ring-azure-600/20",
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "w-full rounded-lg border border-[var(--line)] bg-white/90 px-3 py-2.5 text-sm text-ink outline-none focus:border-azure-600 focus:ring-2 focus:ring-azure-600/20",
        className,
      )}
      {...props}
    />
  );
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "w-full rounded-lg border border-[var(--line)] bg-white/90 px-3 py-2.5 text-sm text-ink outline-none focus:border-azure-600 focus:ring-2 focus:ring-azure-600/20",
        className,
      )}
      {...props}
    />
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "gold" | "mint" | "rose" | "ok" | "blue";
}) {
  const tones = {
    neutral: "bg-white/70 text-slate-600",
    gold: "bg-brand-50 text-brand-700",
    mint: "bg-brand-50 text-brand-700",
    rose: "bg-rose-50 text-rose-700",
    ok: "bg-emerald-50 text-emerald-700",
    blue: "bg-azure-50 text-azure-700",
  };
  return (
    <span className={cn("inline-flex rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide", tones[tone])}>
      {children}
    </span>
  );
}

export function Score({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-[var(--muted)]">—</span>;
  const tone = value >= 70 ? "ok" : value >= 45 ? "gold" : "rose";
  return <Badge tone={tone}>{value}</Badge>;
}

export function Drawer({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-navy/20 backdrop-blur-sm">
      <button className="flex-1" onClick={onClose} aria-label="Close drawer" />
      <aside className="glass-strong h-full w-full max-w-xl overflow-auto border-l p-6">
        <div className="mb-6 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-navy">{title}</h2>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        </div>
        {children}
      </aside>
    </div>
  );
}

export function FormActions({
  pending,
  onCancel,
  label = "Save",
}: {
  pending?: boolean;
  onCancel: () => void;
  label?: string;
}) {
  return (
    <div className="mt-8 flex justify-end gap-2">
      <Button type="button" variant="ghost" onClick={onCancel}>
        Cancel
      </Button>
      <Button type="submit" disabled={pending}>
        {pending ? "Saving…" : label}
      </Button>
    </div>
  );
}

export function CheckField({
  label,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="flex items-center gap-2 text-sm text-ink">
      <input type="checkbox" className="accent-[var(--brand)]" {...props} />
      {label}
    </label>
  );
}
