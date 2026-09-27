/** On-demand evidence for one event (weather, Sentinel-2 search, NDVI/NBR): its current state and the action that
 * produces it. States come from the backend only: the recorded step outcome (enrichment_state) and the event's jobs.
 * Nothing here invents a value; an unavailable result stays explicitly unavailable. */
import { AlertTriangle, CloudOff, Loader2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { fmtDateTime, relTime } from "../lib/format";
import { actions, useAction } from "../lib/hooks";
import { useSession } from "../lib/session";
import type { EnrichmentStep, EventDetail, EventJob } from "../lib/types";
import { errText, useToast } from "./ui";

export type StepPhase = "not_requested" | "pending" | "ok" | "no_data" | "failed" | "job_failed";

const ERROR_TEXT: Record<string, string> = {
  authentication_failed: "authentication failed",
  timeout: "the provider timed out",
  rate_limited: "the provider is rate-limiting requests",
  service_unavailable: "the provider is unavailable",
  unsupported_data: "the provider does not serve this request",
  processing_failure: "the provider's reply could not be processed",
  invalid_request: "the provider rejected the request",
  invalid_response: "the provider returned an unexpected response",
  network_error: "the provider could not be reached",
  provider_error: "the provider returned an error",
};
/** One wording for every provider failure category (backend services/source_health.ERROR_CATEGORIES). */
export const errorText = (category?: string | null) => (category ? ERROR_TEXT[category] ?? category.replace(/_/g, " ") : "request failed");

/** The latest job that covers `step` (a full enrichment covers every step). */
export function jobFor(ev: EventDetail, kind: EventJob["kind"], step?: string): EventJob | undefined {
  return (ev.jobs ?? [])
    .filter((j) => j.kind === kind && (!step || !j.steps.length || j.steps.includes(step)))
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
}

export function stepPhase(ev: EventDetail, step: string): { phase: StepPhase; state?: EnrichmentStep; job?: EventJob } {
  const state = ev.enrichment_state?.[step];
  const job = jobFor(ev, "enrich_event", step);
  if (job && (job.status === "queued" || job.status === "running")) return { phase: "pending", state, job };
  // a job that failed after the step was last recorded (crash, not a provider answer)
  if (job?.status === "failed" && (!state || (job.finished_at ?? job.created_at) > state.at)) return { phase: "job_failed", state, job };
  if (!state) return { phase: "not_requested" };
  if (state.status === "failed") return { phase: "failed", state, job };
  if (state.status === "no_data") return { phase: "no_data", state, job };
  return { phase: "ok", state, job };
}

/** Why the viewer cannot trigger retrieval, or null when they can. */
export function useRequestBlocker(): string | null {
  const { can, isDemo } = useSession();
  if (isDemo) return "Retrieval is disabled in the read-only demo. Sign in with an analyst account to request it.";
  if (!can("analyst")) return "An analyst can request this for the event.";
  return null;
}

/** Queue enrichment steps for the event; the event query polls until the job finishes. */
export function useRequestSteps(ev: EventDetail, steps: string[]) {
  const qc = useQueryClient();
  const toast = useToast();
  const m = useAction(actions.enrichSteps(ev.public_id, steps), [["jobs"]]);
  const run = async () => {
    try {
      await m.mutateAsync(undefined);
      await qc.invalidateQueries({ queryKey: ["event"] });
    } catch (e) { toast(errText(e), "error"); }
  };
  return { run, sending: m.isPending };
}

export function ActionButton({ onClick, busy, busyLabel, children, disabled, testId }: {
  onClick: () => void; busy?: boolean; busyLabel: string; children: ReactNode; disabled?: boolean; testId?: string;
}) {
  const blocker = useRequestBlocker();
  if (blocker) return <div className="faint enrich-blocker" style={{ fontSize: 11.5 }}>{blocker}</div>;
  return (
    <button className="btn sm" onClick={onClick} disabled={busy || disabled} aria-busy={busy || undefined} data-testid={testId}>
      {busy ? <><Loader2 size={13} className="spin" aria-hidden /> {busyLabel}</> : children}
    </button>
  );
}

/** A state that is not (yet) a result: what is missing, why, what would produce it, and what it will mean. */
export function EvidenceState({ icon: Icon = CloudOff, tone = "neutral", title, children, action, meaning, testId }: {
  icon?: LucideIcon; tone?: "neutral" | "warn" | "busy"; title: string; children?: ReactNode; action?: ReactNode;
  meaning?: ReactNode; testId?: string;
}) {
  return (
    <div className={`evidence-state ${tone}`} role={tone === "busy" ? "status" : undefined} data-testid={testId}>
      <div className="es-head">
        {tone === "busy" ? <Loader2 size={16} className="spin" aria-hidden /> : tone === "warn" ? <AlertTriangle size={16} aria-hidden /> : <Icon size={16} aria-hidden />}
        <b>{title}</b>
      </div>
      {children && <div className="es-body">{children}</div>}
      {meaning && <div className="es-meaning">{meaning}</div>}
      {action && <div className="es-action">{action}</div>}
    </div>
  );
}

export function pendingLabel(job?: EventJob): string {
  if (!job) return "";
  if (job.status === "queued") return job.attempts ? `retrying (attempt ${job.attempts + 1} of ${job.max_attempts})` : `queued ${relTime(job.created_at)}`;
  return `started ${relTime(job.started_at ?? job.created_at)}`;
}

export const at = (iso?: string | null) => (iso ? `${fmtDateTime(iso)} (${relTime(iso)})` : "—");
