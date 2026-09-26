import type { DemoRole, FeaturedEvent } from "../lib/types";

/** Real data the tour points at, resolved from the API at runtime. Never fabricated. */
export interface TourContext {
  /** A real event chosen for the walkthrough by the server (the one carrying the most evidence), or null. */
  featured: FeaturedEvent | null;
  isMobile: boolean;
}

export type Placement = "auto" | "top" | "bottom" | "left" | "right";

export interface TourStep {
  /** Stable id; used for progress persistence and tests. */
  id: string;
  title: string;
  /** Main explanation: short, plain language. */
  body: string | ((ctx: TourContext) => string);
  /** Optional "Why this matters". */
  why?: string;
  /** Optional "How it is generated" (shown under Learn more). */
  how?: string;
  /** Optional limitation, always shown: what this evidence or feature cannot establish. */
  limits?: string;
  /** Optional expandable "Learn more". */
  learnMore?: string;
  /** Glossary keys explained at this step (see glossary.ts). */
  terms?: string[];
  /** `data-tour-id` of the element to spotlight. Omit for a centred card. */
  target?: string;
  placement?: Placement;
  /** Route to show before this step. May depend on real data (e.g. the featured event). */
  route?: string | ((ctx: TourContext) => string | null);
  /** Phone-sized layout overrides; mobile screens differ from desktop. */
  mobile?: { route?: TourStep["route"]; target?: string | null };
  /** Needs the featured event; shown without a spotlight, with `fallback` text, if no event exists. */
  needsEvent?: boolean;
  fallback?: string;
  /** Side effect after the target is visible (e.g. demonstrate search with a real query). */
  action?: (ctx: TourContext) => void;
  /** Undo `action` when the tour leaves this step, so the UI is left as the user found it. */
  cleanup?: () => void;
}

export interface Tour {
  id: DemoRole;
  label: string;
  steps: TourStep[];
  summary: { lead: string; flow: string[] };
}
