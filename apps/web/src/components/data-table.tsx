"use client";

import { cn } from "@/lib/cn";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

export type Column<T> = {
  key: string;
  header: string;
  className?: string;
  cell: (row: T) => ReactNode;
};

export function DataTable<T extends { id: string }>({
  columns,
  rows,
  href,
}: {
  columns: Column<T>[];
  rows: T[];
  href?: (row: T) => string;
}) {
  const router = useRouter();
  return (
    <div className="panel overflow-hidden">
      <div className="max-h-[70vh] overflow-auto">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 z-10 border-b border-[var(--line)] bg-white/80 text-xs font-semibold uppercase tracking-wide text-[var(--muted)] backdrop-blur-md">
            <tr>
              {columns.map((column) => (
                <th key={column.key} className={cn("px-4 py-2.5", column.className)}>
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                className={cn(
                  "border-t border-[var(--line)] bg-white/40 transition hover:bg-azure-50/70",
                  href ? "cursor-pointer" : "",
                )}
                onClick={() => {
                  if (href) router.push(href(row));
                }}
              >
                {columns.map((column) => (
                  <td key={column.key} className={cn("px-4 py-2.5 text-ink", column.className)}>
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
