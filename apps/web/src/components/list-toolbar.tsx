"use client";

import { Button, Input, Select } from "@/components/ui";
import type { ReactNode } from "react";

export function ListToolbar({
  query,
  onQuery,
  filter,
  onFilter,
  filterOptions,
  onCreate,
  createLabel,
  extra,
}: {
  query: string;
  onQuery: (value: string) => void;
  filter?: string;
  onFilter?: (value: string) => void;
  filterOptions?: { value: string; label: string }[];
  onCreate?: () => void;
  createLabel?: string;
  extra?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <Input
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        placeholder="Filter this list"
        className="max-w-sm"
      />
      {filterOptions && onFilter ? (
        <Select value={filter} onChange={(e) => onFilter(e.target.value)} className="max-w-[200px]">
          {filterOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      ) : null}
      <div className="ml-auto flex gap-2">
        {extra}
        {onCreate ? <Button onClick={onCreate}>{createLabel ?? "Create"}</Button> : null}
      </div>
    </div>
  );
}
