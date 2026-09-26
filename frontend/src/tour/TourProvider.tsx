/** Guided-tour state for read-only demo sessions: which tour, which step, and moving the real app to it.
 *  Persisted in sessionStorage (no credentials): `thermaltrace_demo_role`, `thermaltrace_tour_progress`. */
import { useQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useIsMobile, useSession } from "../lib/session";
import type { DemoRole, FeaturedEvent } from "../lib/types";
import { TOURS } from "./tours";
import type { Tour, TourContext, TourStep } from "./types";

export const DEMO_ROLE_KEY = "thermaltrace_demo_role";
export const PROGRESS_KEY = "thermaltrace_tour_progress";

export type TourStatus = "running" | "closed" | "done";
interface Progress { role: DemoRole; index: number; status: TourStatus }

interface TourCtx {
  tour: Tour | null;
  step: TourStep | null;
  index: number;
  status: TourStatus;
  ctx: TourContext;
  next: () => void;
  back: () => void;
  skip: () => void;
  restart: () => void;
  close: () => void;
}

const Ctx = createContext<TourCtx | null>(null);

function readProgress(): Progress | null {
  try {
    const raw = sessionStorage.getItem(PROGRESS_KEY);
    return raw ? (JSON.parse(raw) as Progress) : null;
  } catch {
    return null;
  }
}

function writeProgress(p: Progress | null) {
  try {
    if (p) {
      sessionStorage.setItem(PROGRESS_KEY, JSON.stringify(p));
      sessionStorage.setItem(DEMO_ROLE_KEY, p.role);
    } else {
      sessionStorage.removeItem(PROGRESS_KEY);
      sessionStorage.removeItem(DEMO_ROLE_KEY);
    }
  } catch {
    /* storage unavailable: the tour still works for this page view */
  }
}

export function clearTourState() {
  writeProgress(null);
}

/** A real event for the walkthrough, chosen server-side from live data by how much evidence it carries (facility,
 *  classification, confidence, persistence, land cover, imagery analysis), then triage priority. Never hard-coded. */
async function pickFeatured(): Promise<FeaturedEvent | null> {
  return api<FeaturedEvent | null>("/events/featured");
}

export function resolveRoute(step: TourStep, ctx: TourContext): string | null {
  const r = (ctx.isMobile && step.mobile && "route" in step.mobile ? step.mobile.route : step.route) ?? null;
  return typeof r === "function" ? r(ctx) : r;
}

export function resolveTarget(step: TourStep, ctx: TourContext): string | null {
  if (step.needsEvent && !ctx.featured) return null;
  if (ctx.isMobile && step.mobile && "target" in step.mobile) return step.mobile.target ?? null;
  return step.target ?? null;
}

export function TourProvider({ children }: { children: ReactNode }) {
  const { user, isDemo, loading } = useSession();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const location = useLocation();
  const role = isDemo && user && (user.role === "analyst" || user.role === "admin") ? (user.role as DemoRole) : null;
  const [progress, setProgress] = useState<Progress | null>(() => readProgress());

  const featuredQ = useQuery({ queryKey: ["tour-featured", role], queryFn: pickFeatured, enabled: !!role, staleTime: 10 * 60_000 });
  const ctx = useMemo<TourContext>(() => ({ featured: featuredQ.data ?? null, isMobile }), [featuredQ.data, isMobile]);

  // A new demo session (or a role switch) starts its own tour from step 1; no demo session means no tour state.
  useEffect(() => {
    if (loading) return; // a reload mid-tour keeps its place once the session is known
    if (!role) { setProgress(null); writeProgress(null); return; }
    setProgress((p) => (p && p.role === role ? p : { role, index: 0, status: "running" }));
  }, [role, loading]);
  useEffect(() => { if (role && progress) writeProgress(progress); }, [role, progress]);

  const tour = role ? TOURS[role] : null;
  const active = tour && progress && progress.role === role ? progress : null;
  const index = active ? Math.min(active.index, tour!.steps.length - 1) : 0;
  const status: TourStatus = active?.status ?? "closed";
  // Only steps about the featured event wait for it; the rest of the tour never blocks on that lookup.
  const candidate = tour && status === "running" ? tour.steps[index] : null;
  const step = candidate && !(candidate.needsEvent && featuredQ.isLoading) ? candidate : null;

  // Move the real app to the step's route. The overlay then waits for the target to mount.
  const route = step ? resolveRoute(step, ctx) : null;
  useEffect(() => {
    if (!route) return;
    const here = location.pathname + location.search;
    const [path, search = ""] = route.split("?");
    const matches = location.pathname === path && (!search || location.search === `?${search}`);
    if (!matches && here !== route) navigate(route);
  }, [route, location.pathname, location.search, navigate]);

  const set = useCallback((f: (p: Progress) => Progress) => setProgress((p) => (p ? f(p) : p)), []);
  const value = useMemo<TourCtx>(() => ({
    tour, step, index, status, ctx,
    next: () => set((p) => (p.index >= tour!.steps.length - 1 ? { ...p, status: "done" } : { ...p, index: p.index + 1 })),
    back: () => set((p) => ({ ...p, index: Math.max(0, p.index - 1) })),
    skip: () => set((p) => ({ ...p, status: "closed" })),
    close: () => set((p) => ({ ...p, status: "closed" })),
    restart: () => set((p) => ({ ...p, index: 0, status: "running" })),
  }), [tour, step, index, status, ctx, set]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTour(): TourCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTour outside TourProvider");
  return v;
}
