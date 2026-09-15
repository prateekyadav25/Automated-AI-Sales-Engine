"use client";

import { api, readToken, writeToken } from "@agrayian/sdk";
import type { TokenUser } from "@agrayian/types";
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";

type AuthState = {
  user: TokenUser | null;
  loading: boolean;
  can: (permission: string) => boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

type SessionPayload = { access_token: string; user: TokenUser };

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<TokenUser | null>(null);
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);

  useEffect(() => {
    const gen = generation.current;
    let cancelled = false;

    const apply = (res: { data?: SessionPayload | null }) => {
      if (cancelled || gen !== generation.current || !res.data) return false;
      writeToken(res.data.access_token);
      setUser(res.data.user);
      return true;
    };

    async function restore() {
      try {
        if (readToken()) {
          if (apply(await api<SessionPayload>("/api/v1/auth/me"))) return;
        }
        apply(await api<SessionPayload>("/api/v1/auth/refresh", { method: "POST" }));
      } catch {
        if (!cancelled && gen === generation.current) {
          writeToken(null);
          setUser(null);
        }
      } finally {
        if (!cancelled && gen === generation.current) setLoading(false);
      }
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      can: (permission) => Boolean(user?.permissions.includes(permission)),
      login: async (email, password) => {
        generation.current += 1;
        writeToken(null);
        const res = await api<SessionPayload>("/api/v1/auth/login", {
          method: "POST",
          body: JSON.stringify({ email, password }),
        });
        if (!res.data) throw new Error("Login failed");
        writeToken(res.data.access_token);
        setUser(res.data.user);
        setLoading(false);
      },
      logout: async () => {
        generation.current += 1;
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
