"use client";

import { ApiError, api, readToken, writeToken } from "@agrayian/sdk";
import type { TokenUser } from "@agrayian/types";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

type AuthState = {
  user: TokenUser | null;
  loading: boolean;
  can: (permission: string) => boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<TokenUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function restore() {
      const apply = (res: { data?: { access_token: string; user: TokenUser } | null }) => {
        if (res.data) {
          writeToken(res.data.access_token);
          setUser(res.data.user);
          return true;
        }
        return false;
      };
      try {
        if (readToken()) {
          try {
            apply(await api<{ access_token: string; user: TokenUser }>("/api/v1/auth/me"));
            return;
          } catch (error) {
            if (!(error instanceof ApiError) || error.status !== 401) throw error;
          }
          apply(await api<{ access_token: string; user: TokenUser }>("/api/v1/auth/refresh", { method: "POST" }));
          return;
        }
        setUser(null);
      } catch {
        setUser(null);
      } finally {
        setLoading(false);
      }
    }
    void restore();
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      can: (permission) => Boolean(user?.permissions.includes(permission)),
      login: async (email, password) => {
        const res = await api<{ access_token: string; user: TokenUser }>("/api/v1/auth/login", {
          method: "POST",
          body: JSON.stringify({ email, password }),
        });
        if (!res.data) throw new Error("Login failed");
        writeToken(res.data.access_token);
        setUser(res.data.user);
      },
      logout: async () => {
        await api("/api/v1/auth/logout", { method: "POST" }).catch(() => undefined);
        writeToken(null);
        setUser(null);
      },
    }),
    [user, loading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("AuthProvider missing");
  return ctx;
}
