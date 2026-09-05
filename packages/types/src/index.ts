export type Envelope<T> = {
  data: T | null;
  meta: { page: number; page_size: number; total: number } | null;
  error: { code: string; message: string } | null;
};

export type TokenUser = {
  id: string;
  tenant_id: string;
  email: string;
  name: string;
  roles: string[];
  permissions: string[];
  is_super_admin: boolean;
};
