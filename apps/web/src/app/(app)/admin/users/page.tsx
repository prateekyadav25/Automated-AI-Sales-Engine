"use client";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { DeniedState, EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { api } from "@agrayian/sdk";
import { useQuery } from "@tanstack/react-query";

type UserRow = { id: string; email: string; name: string; roles: string[]; is_active: boolean };

export default function AdminUsersPage() {
  const { can } = useAuth();
  const query = useQuery({
    queryKey: ["users"],
    queryFn: async () => (await api<UserRow[]>("/api/v1/admin/users")).data ?? [],
    enabled: can("users.read"),
  });
  if (!can("users.read")) return <DeniedState />;
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message="People could not be assembled." />;
  const rows = query.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="House"
        title="People"
        subtitle="Tenant-scoped identity. Authority is a permission string, never a role name in product code."
      />
      {rows.length === 0 ? (
        <EmptyState title="No people" body="Seed creates the first tenant admin." />
      ) : (
        <DataTable
          rows={rows}
          columns={[
            { key: "name", header: "Name", cell: (row) => row.name },
            { key: "email", header: "Email", cell: (row) => row.email },
            { key: "roles", header: "Roles", cell: (row) => row.roles.join(" · ") || "—" },
            {
              key: "active",
              header: "State",
              cell: (row) => <Badge tone={row.is_active ? "ok" : "rose"}>{row.is_active ? "active" : "disabled"}</Badge>,
            },
          ]}
        />
      )}
    </div>
  );
}
