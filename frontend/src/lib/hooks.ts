import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, del, post, put } from "./api";
import type {
  Alert, AlertRule, DataSource, EventDetail, EventSummary, Facility, Job, Page, Report, SystemStatus, Watchlist,
} from "./types";

export interface EventFilters {
  classification?: string[];
  persistence?: string[];
  confidence_state?: string[];
  review_status?: string[];
  status?: string[];
  data_mode?: string[];
  sensor?: string[];
  facility_type?: string[];
  min_frp?: number;
  min_confidence?: number;
  min_observations?: number;
  since?: string;
  q?: string;
}

export function sinceFromDays(days: number | null): string | undefined {
  if (!days) return undefined;
  return new Date(Date.now() - days * 86_400_000).toISOString();
}

export const useStatus = () =>
  useQuery({ queryKey: ["status"], queryFn: () => api<SystemStatus>("/status"), refetchInterval: 60_000 });

export const useEvents = (filters: EventFilters, sort: string, limit: number, offset: number) =>
  useQuery({
    queryKey: ["events", filters, sort, limit, offset],
    queryFn: () => api<Page<EventSummary>>("/events", { query: { ...filters, sort, limit, offset } as never }),
    placeholderData: keepPreviousData,
  });

export const useEvent = (ref: string | undefined) =>
  useQuery({ queryKey: ["event", ref], queryFn: () => api<EventDetail>(`/events/${ref}`), enabled: !!ref });

export const useSimilar = (ref: string | undefined) =>
  useQuery({ queryKey: ["similar", ref], queryFn: () => api<EventSummary[]>(`/events/${ref}/similar`), enabled: !!ref });

export const useFacilities = (params: Record<string, unknown>) =>
  useQuery({
    queryKey: ["facilities", params],
    queryFn: () => api<Page<Facility>>("/facilities", { query: params as never }),
    placeholderData: keepPreviousData,
  });

export const useAlerts = (status?: string) =>
  useQuery({ queryKey: ["alerts", status], queryFn: () => api<Page<Alert>>("/alerts", { query: { status, limit: 100 } }), refetchInterval: 60_000 });

export const useUnread = () =>
  useQuery({ queryKey: ["alerts-unread"], queryFn: () => api<{ count: number }>("/alerts/unread-count"), refetchInterval: 60_000 });

export const useRules = () => useQuery({ queryKey: ["rules"], queryFn: () => api<AlertRule[]>("/alert-rules") });
export const useWatchlists = () => useQuery({ queryKey: ["watchlists"], queryFn: () => api<Watchlist[]>("/watchlists") });
export const useReports = (eventId?: string) =>
  useQuery({
    queryKey: ["reports", eventId],
    queryFn: () => api<Page<Report>>("/reports", { query: { event_id: eventId, limit: 100 } }),
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === "pending") ? 2000 : false),
  });
export const useSources = () => useQuery({ queryKey: ["sources"], queryFn: () => api<DataSource[]>("/sources"), refetchInterval: 60_000 });
export const useJobs = () =>
  useQuery({ queryKey: ["jobs"], queryFn: () => api<Page<Job>>("/jobs", { query: { limit: 30 } }), refetchInterval: 10_000 });

/** Mutation that invalidates the given query keys on success. */
export function useAction<TBody, TRes = unknown>(fn: (body: TBody) => Promise<TRes>, invalidate: unknown[][]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k })),
  });
}

export const actions = {
  review: (ref: string) => (body: Record<string, unknown>) => post(`/events/${ref}/reviews`, body),
  note: (ref: string) => (body: { body: string; url?: string }) => post(`/events/${ref}/notes`, body),
  enrich: (ref: string) => () => post<{ job_id: string }>(`/events/${ref}/enrich`),
  report: () => (eventId: string) => post<Report>("/reports", { event_id: eventId }),
  createRule: () => (body: Record<string, unknown>) => post<AlertRule>("/alert-rules", body),
  updateRule: (id: string) => (body: Record<string, unknown>) => put<AlertRule>(`/alert-rules/${id}`, body),
  deleteRule: () => (id: string) => del(`/alert-rules/${id}`),
  createWatchlist: () => (body: { name: string; description?: string }) => post<Watchlist>("/watchlists", body),
  addWatchItem: (id: string) => (body: Record<string, unknown>) => post<Watchlist>(`/watchlists/${id}/items`, body),
  removeWatchItem: (id: string) => (itemId: string) => del(`/watchlists/${id}/items/${itemId}`),
  deleteWatchlist: () => (id: string) => del(`/watchlists/${id}`),
  alertAction: () => ({ id, action }: { id: string; action: "acknowledge" | "resolve" }) => post(`/alerts/${id}/${action}`),
};
