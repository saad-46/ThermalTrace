import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { api, auth, post } from "./api";
import type { DemoRole, Role, User } from "./types";

const RANK: Record<Role, number> = { viewer: 0, analyst: 1, supervisor: 2, admin: 3 };

interface SessionCtx {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (min: Role) => boolean;
  /** True for read-only guided exploration sessions. */
  isDemo: boolean;
  /** Start a read-only demo session for a role (no credentials; the server decides whether this is enabled). */
  startDemo: (role: DemoRole) => Promise<void>;
}

const Ctx = createContext<SessionCtx | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const token = useSyncExternalStore(auth.subscribe, () => auth.token);
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me", token], queryFn: () => api<User>("/auth/me"), enabled: !!token, retry: false, staleTime: 5 * 60_000 });

  const value = useMemo<SessionCtx>(
    () => ({
      user: token ? me.data ?? null : null,
      loading: !!token && me.isLoading,
      async login(email, password) {
        const res = await post<{ access_token: string; user: User }>("/auth/login", { email, password });
        qc.clear();
        auth.set(res.access_token);
        qc.setQueryData(["me", res.access_token], res.user);
      },
      async logout() {
        try {
          await post("/auth/logout");
        } finally {
          auth.set(null);
          qc.clear();
        }
      },
      can(min) {
        const u = token ? me.data : null;
        return !!u && RANK[u.role] >= RANK[min];
      },
      isDemo: !!(token && me.data?.is_demo),
      async startDemo(role) {
        if (auth.token) {
          // Switching roles: end the current demo session first so no demo privileges linger.
          try { await post("/auth/logout"); } catch { /* already expired */ }
        }
        const res = await post<{ access_token: string; user: User }>("/auth/demo", { role });
        qc.clear();
        auth.set(res.access_token);
        qc.setQueryData(["me", res.access_token], res.user);
      },
    }),
    [token, me.data, me.isLoading, qc],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): SessionCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession outside SessionProvider");
  return v;
}

export function useMedia(query: string): boolean {
  const [match, setMatch] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatch(mq.matches);
    mq.addEventListener("change", on);
    on();
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return match;
}

export const useIsMobile = () => useMedia("(max-width: 767px)");

type Theme = "light" | "dark";
export function useTheme(): [Theme, (t: Theme) => void] {
  const prefersDark = useMedia("(prefers-color-scheme: dark)");
  const [stored, setStored] = useState<Theme | null>(() => {
    try {
      return (localStorage.getItem("tt.theme") as Theme | null) ?? null;
    } catch {
      return null;
    }
  });
  const theme: Theme = stored ?? (prefersDark ? "dark" : "light");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  return [
    theme,
    (t) => {
      setStored(t);
      try {
        localStorage.setItem("tt.theme", t);
      } catch {
        /* ignore */
      }
    },
  ];
}
