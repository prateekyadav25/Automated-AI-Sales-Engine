import type { ButtonHTMLAttributes } from "react";

export function Button({ className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-md bg-teal-400 px-3 py-2 text-sm font-medium text-slate-950 disabled:opacity-50 ${className}`}
      {...props}
    />
  );
}
