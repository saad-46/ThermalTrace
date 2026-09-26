import { Bell, ChevronLeft, Eye, List, LocateFixed, Map as MapIcon, Menu } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useMemo, useRef, useState, type PointerEvent as RPE, type ReactNode } from "react";
import { Link, Navigate, NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ConfidenceBreakdown, EvidenceList, EvidenceMatrix, FacilityList, Fingerprint, ModelPanel, PersistencePanel, Timeline } from "../components/evidence";
import { DEFAULT_FILTERS, FilterPanel, TimeRange, toQuery, type FilterState } from "../components/filters";
import { EventActions, EventHeader, ReviewPanel, SatellitePanel, WeatherPanel } from "../components/investigation";
import { LandCoverPanel, SpectralChangePanel } from "../components/landcover";
import GlobalSearch from "../components/GlobalSearch";
import MapCanvas, { DEFAULT_LAYERS } from "../components/MapCanvas";
import { EvidenceChain, PriorityPanel, PriorityPill } from "../components/triage";
import { Async, Boundary, ClassLabel, DemoBanner, Empty, ErrorState, Freshness, Skeleton, StatePill, errText, useToast } from "../components/ui";
import { api } from "../lib/api";
import { coordsLabel, fmtDistance, locationLabel, relTime } from "../lib/format";
import { actions, useAction, useAlerts, useEvent, useEvents, useUnread, useWatchlists } from "../lib/hooks";
import { useSession, useTheme } from "../lib/session";
import type { EventDetail, EventSummary, Page } from "../lib/types";
import ExploreBanner from "../tour/ExploreBanner";

// Desktop pages that also work in the phone shell (used by the overview and the admin views of the guided tour).
const Overview = lazy(() => import("../pages/Overview"));
const DataSources = lazy(() => import("../pages/DataSources"));
const SystemHealth = lazy(() => import("../pages/SystemHealth"));
const Analytics = lazy(() => import("../pages/Analytics"));
const Settings = lazy(() => import("../pages/Settings"));

// ------------------------------------------------------------------ shell
function Shell({ title, back, right, children }: { title: ReactNode; back?: boolean; right?: ReactNode; children: ReactNode }) {
  const nav = useNavigate();
  const unread = useUnread();
  return (
    <div className="m-shell">
      <header className="m-top">
        {back ? <button className="btn ghost icon" onClick={() => nav(-1)} aria-label="Back"><ChevronLeft size={18} /></button> : <span className="brand-mark" aria-hidden />}
        <div style={{ fontWeight: 600, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
        {right}
      </header>
      <ExploreBanner compact />
      <DemoBanner />
      <main className="m-main">{children}</main>
      <nav className="m-nav" aria-label="Primary">
        <NavLink to="/map" className={({ isActive }) => (isActive ? "active" : "")}><MapIcon size={19} strokeWidth={1.75} />Map</NavLink>
        <NavLink to="/events" className={({ isActive }) => (isActive ? "active" : "")}><List size={19} strokeWidth={1.75} />Events</NavLink>
        <NavLink to="/alerts" className={({ isActive }) => (isActive ? "active" : "")}><Bell size={19} strokeWidth={1.75} />Alerts{unread.data?.count ? <span className="badge">{unread.data.count}</span> : null}</NavLink>
        <NavLink to="/watchlist" className={({ isActive }) => (isActive ? "active" : "")}><Eye size={19} strokeWidth={1.75} />Watchlist</NavLink>
        <NavLink to="/more" className={({ isActive }) => (isActive ? "active" : "")}><Menu size={19} strokeWidth={1.75} />More</NavLink>
      </nav>
    </div>
  );
}

// ------------------------------------------------------------------ bottom sheet
const SNAPS = [0.2, 0.55, 0.92];
function Sheet({ children, snap, setSnap }: { children: ReactNode; snap: number; setSnap: (i: number) => void }) {
  const drag = useRef<{ y: number; h: number } | null>(null);
  const [live, setLive] = useState<number | null>(null);
  const parentH = () => (document.querySelector(".m-main") as HTMLElement | null)?.clientHeight ?? window.innerHeight;
  const down = (e: RPE) => { (e.target as HTMLElement).setPointerCapture(e.pointerId); drag.current = { y: e.clientY, h: SNAPS[snap] * parentH() }; };
  const move = (e: RPE) => { if (drag.current) setLive(Math.max(80, drag.current.h + (drag.current.y - e.clientY))); };
  const up = () => {
    if (drag.current && live != null) {
      const frac = live / parentH();
      setSnap(SNAPS.reduce((best, s, i) => (Math.abs(s - frac) < Math.abs(SNAPS[best] - frac) ? i : best), 0));
    }
    drag.current = null;
    setLive(null);
  };
  return (
    <section className="sheet" data-tour-id="map-event-sheet" style={{ height: live ?? `${SNAPS[snap] * 100}%`, transition: live != null ? "none" : undefined }} aria-label="Event details">
      <div className="grab" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
        role="button" tabIndex={0} aria-label="Resize panel" onKeyDown={(e) => { if (e.key === "ArrowUp") setSnap(Math.min(2, snap + 1)); if (e.key === "ArrowDown") setSnap(Math.max(0, snap - 1)); }}>
        <i />
      </div>
      <div className="sheet-body">{children}</div>
    </section>
  );
}

// ------------------------------------------------------------------ evidence cards (swipeable)
const CARD_TOUR_IDS: Record<string, string> = {
  "How ThermalTrace thinks": "card-evidence-chain", Facilities: "card-facilities", Persistence: "card-persistence", "Land cover": "card-landcover",
  "Spectral change": "card-spectral", "Model evidence": "card-model",
};
function EvidenceCards({ ev }: { ev: EventDetail }) {
  const cards: [string, ReactNode][] = [
    ["How ThermalTrace thinks", <EvidenceChain ev={ev} key="ch" />],
    ["Evidence matrix", <div className="table-wrap" key="m"><EvidenceMatrix ev={ev} /></div>],
    ["Why prioritised", <PriorityPanel p={ev.priority_components} key="pr" />],
    ["Confidence", <ConfidenceBreakdown ev={ev} key="c" />],
    ["Facilities", <div className="table-wrap" key="f"><FacilityList ev={ev} /></div>],
    ["Persistence", <PersistencePanel ev={ev} key="p" />],
    ["Land cover", <LandCoverPanel ev={ev} key="lc" />],
    ["Spectral change", <SpectralChangePanel ev={ev} key="sc" />],
    ["Satellite", <SatellitePanel ev={ev} key="s" />],
    ["Weather", <WeatherPanel ev={ev} key="w" />],
    ["Model evidence", <ModelPanel ev={ev} key="md" />],
    ["Fingerprint", <Fingerprint ev={ev} key="fp" />],
  ];
  return (
    <div className="cards" role="list" aria-label="Evidence cards (swipe)">
      {cards.map(([t, c]) => (
        <div key={t} className="panel" role="listitem" data-tour-id={CARD_TOUR_IDS[t]}><div className="panel-head"><h3>{t}</h3></div><div className="panel-body" style={{ maxHeight: 420, overflow: "auto" }}>{c}</div></div>
      ))}
    </div>
  );
}

function EventSheetContent({ id, expanded }: { id: string; expanded: boolean }) {
  const ev = useEvent(id);
  if (ev.isLoading) return <div className="panel-body"><Skeleton lines={4} /></div>;
  if (ev.error || !ev.data) return <ErrorState error={ev.error} retry={() => ev.refetch()} />;
  const e = ev.data;
  return (
    <div>
      <div className="section" style={{ paddingTop: 0 }}>
        <EventHeader ev={e} />
        <div className="row wrap" style={{ marginTop: 8 }}>
          <Link className="btn sm primary" to={`/events/${e.public_id}`}>Investigate</Link>
          <span className="faint" style={{ fontSize: 12 }}>{e.facilities[0] ? `${fmtDistance(e.facilities[0].distance_m)} from ${e.facilities[0].name ?? e.facilities[0].facility_type}` : "No mapped facility nearby"}</span>
        </div>
      </div>
      {expanded && <EvidenceCards ev={e} />}
    </div>
  );
}

// ------------------------------------------------------------------ screens
function MapScreen() {
  const [params, setParams] = useSearchParams();
  const sel = params.get("event");
  const [theme] = useTheme();
  const [f, setF] = useState<FilterState>(DEFAULT_FILTERS);
  const [showFilters, setShowFilters] = useState(false);
  const [snap, setSnap] = useState(0);
  const [flyTo, setFlyTo] = useState<{ lat: number; lon: number; zoom?: number } | null>(null);
  const toast = useToast();
  const query = useMemo(() => toQuery(f), [f]);
  const ev = useEvent(sel ?? undefined);
  const locate = () => navigator.geolocation?.getCurrentPosition(
    (p) => setFlyTo({ lat: p.coords.latitude, lon: p.coords.longitude, zoom: 9 }),
    () => toast("Location unavailable — check permissions", "error"), { timeout: 10000 });
  return (
    <Shell title={<Freshness compact />} right={<button className="btn ghost icon" onClick={locate} aria-label="Go to my location"><LocateFixed size={18} /></button>}>
      <div style={{ position: "absolute", inset: 0 }} data-tour-id="map-canvas">
        <Boundary label="Map">
          <MapCanvas filters={query} layers={DEFAULT_LAYERS} theme={theme} selectedId={ev.data?.id ?? sel} focus={ev.data ?? null} flyTo={flyTo}
            onSelect={(id) => { setParams(id ? { event: id } : {}); setSnap(id ? 1 : 0); }} />
        </Boundary>
        <div className="map-overlay map-toolbar">
          <TimeRange value={f.days} onChange={(days) => setF({ ...f, days })} />
          <button className="btn" onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters}>Filters</button>
        </div>
        {showFilters && <div className="float" style={{ position: "absolute", top: 52, left: 8, right: 8, zIndex: 30, maxHeight: "70%", overflow: "auto" }}><FilterPanel f={f} set={setF} onClose={() => setShowFilters(false)} /></div>}
        {sel && <Sheet snap={snap} setSnap={setSnap}><EventSheetContent id={sel} expanded={snap > 0} /></Sheet>}
      </div>
    </Shell>
  );
}

function EventItem({ e }: { e: EventSummary }) {
  return (
    <Link to={`/events/${e.public_id}`} className="item">
      <i style={{ width: 4, alignSelf: "stretch", borderRadius: 2, background: "var(--border-strong)" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="row" style={{ justifyContent: "space-between" }}><span className="mono">{e.public_id}</span><span className="faint" style={{ fontSize: 12 }}>{relTime(e.last_detected)}</span></div>
        <div className="faint" style={{ fontSize: 12.5 }}>{locationLabel(e) || "Unnamed"} <span className="mono" style={{ fontSize: 11 }}>{coordsLabel(e)}</span></div>
        <div className="row wrap" style={{ marginTop: 4 }}><ClassLabel cls={e.classification} short /><StatePill state={e.display_state} /><PriorityPill score={e.priority_score} /></div>
      </div>
    </Link>
  );
}

function EventsScreen() {
  const [queue, setQueue] = useState<"priority" | "recent" | "review" | "persistent" | "near">("priority");
  const [near, setNear] = useState<{ lat: number; lon: number } | null>(null);
  const toast = useToast();
  const filters = queue === "review" ? { confidence_state: ["INSUFFICIENT_EVIDENCE", "LOW_CONFIDENCE"], min_observations: 2 }
    : queue === "persistent" ? { persistence: ["persistent"] } : {};
  const list = useEvents(filters, queue === "persistent" ? "persistence" : queue === "priority" ? "priority" : "last_detected", 50, 0);
  const nearby = useAsyncNear(near);
  const findNear = () => navigator.geolocation?.getCurrentPosition((p) => { setNear({ lat: p.coords.latitude, lon: p.coords.longitude }); setQueue("near"); },
    () => toast("Location unavailable — check permissions", "error"), { timeout: 10000 });
  return (
    <Shell title="Events">
      <div style={{ padding: "8px 12px 0" }}><GlobalSearch compact /></div>
      <div style={{ padding: "8px 12px", display: "flex", gap: 6, overflowX: "auto" }} className="chips">
        {([["priority", "Priority"], ["recent", "Recent"], ["review", "Needs review"], ["persistent", "Persistent"]] as const).map(([k, l]) => (
          <button key={k} className={`chip ${queue === k ? "on" : ""}`} onClick={() => setQueue(k)}>{l}</button>))}
        <button className={`chip ${queue === "near" ? "on" : ""}`} onClick={findNear}><LocateFixed size={12} /> Near me</button>
      </div>
      <div className="m-list" data-tour-id="events-list">
        {queue === "near"
          ? <Async q={nearby} empty={(d) => (d.items.length ? null : <Empty title="No events within 50 km" />)}>{(d) => <>{d.items.map((e) => <EventItem key={e.id} e={e} />)}</>}</Async>
          : <Async q={list} empty={(d) => (d.items.length ? null : <Empty title="No events" />)}>{(d) => <>{d.items.map((e) => <EventItem key={e.id} e={e} />)}</>}</Async>}
      </div>
    </Shell>
  );
}

function useAsyncNear(p: { lat: number; lon: number } | null) {
  const d = 0.45; // ≈50 km
  return useQuery({
    queryKey: ["near", p?.lat, p?.lon],
    enabled: !!p,
    queryFn: () => api<Page<EventSummary>>("/events", { query: { bbox: `${p!.lon - d},${p!.lat - d},${p!.lon + d},${p!.lat + d}`, limit: 100 } }),
  });
}

function EventScreen() {
  const { ref } = useParams();
  const ev = useEvent(ref);
  const [tab, setTab] = useState<"evidence" | "review" | "timeline" | "all">("evidence");
  return (
    <Shell title={<span className="mono">{ref}</span>} back>
      {ev.isLoading ? <div className="page"><Skeleton lines={8} /></div> : ev.error || !ev.data ? <ErrorState error={ev.error} retry={() => ev.refetch()} /> : (
        <div>
          <div className="section"><div data-tour-id="event-header"><EventHeader ev={ev.data} /></div><div style={{ marginTop: 10 }} data-tour-id="event-actions"><EventActions ev={ev.data} compact /></div></div>
          <div className="tabs" data-tour-id="event-tabs">{(["evidence", "review", "timeline", "all"] as const).map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t === "all" ? "Evidence list" : t[0].toUpperCase() + t.slice(1)}</button>)}</div>
          {tab === "evidence" && <div style={{ paddingTop: 10 }}><EvidenceCards ev={ev.data} /></div>}
          {tab === "review" && <div className="section"><ReviewPanel ev={ev.data} /></div>}
          {tab === "timeline" && <div className="section"><Timeline ev={ev.data} /></div>}
          {tab === "all" && <div className="section"><EvidenceList items={ev.data.evidence} compact /></div>}
        </div>
      )}
    </Shell>
  );
}

function AlertsScreen() {
  const alerts = useAlerts();
  const act = useAction(actions.alertAction(), [["alerts"], ["alerts-unread"]]);
  return (
    <Shell title="Alerts">
      <div className="m-list" data-tour-id="alerts-list">
        <Async q={alerts} empty={(d) => (d.items.length ? null : <Empty title="No alerts">Rules are managed on desktop or under More.</Empty>)}>{(d) => <>{d.items.map((a) => (
          <div key={a.id} className="item" style={{ flexDirection: "column", gap: 4 }}>
            <Link to={`/events/${a.event_public_id}`} style={{ fontWeight: a.status === "new" ? 600 : 400, color: "var(--text)" }}>{a.title}</Link>
            <div className="faint" style={{ fontSize: 12 }}>{a.rule_name} · {a.severity} · {relTime(a.triggered_at)}</div>
            {a.status === "new" && <div><button className="btn sm" onClick={() => act.mutate({ id: a.id, action: "acknowledge" })}>Acknowledge</button></div>}
          </div>
        ))}</>}</Async>
      </div>
    </Shell>
  );
}

function WatchlistScreen() {
  const wls = useWatchlists();
  return (
    <Shell title="Watchlist">
      <Async q={wls} empty={(d) => (d.length ? null : <Empty title="No watchlists">Use "Watch area" on an event to start monitoring.</Empty>)}>{(d) => (
        <div className="m-list">{d.map((w) => (
          <Link key={w.id} to={`/watchlist/${w.id}`} className="item" style={{ flexDirection: "column", gap: 2 }}>
            <b>{w.name}</b>
            <span className="faint" style={{ fontSize: 12.5 }}>{w.summary.events} events · {w.summary.persistent} persistent · {w.summary.new_since_viewed} new · {w.items.length} target(s)</span>
          </Link>
        ))}</div>
      )}</Async>
    </Shell>
  );
}

function WatchlistEventsScreen() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["watch-events", id], queryFn: () => api<{ items: EventSummary[] }>(`/watchlists/${id}/events`) });
  return (
    <Shell title="Watchlist events" back>
      <div className="m-list"><Async q={q} empty={(d) => (d.items.length ? null : <Empty title="No matching events" />)}>{(d) => <>{d.items.map((e) => <EventItem key={e.id} e={e} />)}</>}</Async></div>
    </Shell>
  );
}

function MoreScreen() {
  const { user, logout } = useSession();
  const [theme, setTheme] = useTheme();
  const toast = useToast();
  const reportsQ = useQuery({ queryKey: ["reports", "recent"], queryFn: () => api<Page<{ id: string; title: string; status: string }>>("/reports", { query: { limit: 5 } }) });
  const reports = reportsQ.data?.items ?? [];
  return (
    <Shell title="More">
      <div className="page stack" style={{ gap: 12 }}>
        <div className="panel panel-body"><b>{user?.full_name}</b><div className="faint">{user?.email} · {user?.role}</div></div>
        <div className="panel panel-body stack">
          <h4>Data freshness</h4><Freshness />
        </div>
        <div className="panel panel-body stack">
          <h4>Recent reports</h4>
          {reports.length ? reports.map((r) => <div key={r.id} className="row" style={{ justifyContent: "space-between" }}><span>{r.title}</span><span className="faint">{r.status}</span></div>) : <span className="faint">No reports yet.</span>}
        </div>
        <div className="panel panel-body row" style={{ justifyContent: "space-between" }}>
          <span>Dark theme</span><input type="checkbox" aria-label="Dark theme" checked={theme === "dark"} onChange={(e) => setTheme(e.target.checked ? "dark" : "light")} />
        </div>
        <nav className="panel panel-body stack" aria-label="More views" style={{ gap: 6 }}>
          <Link to="/overview">Overview</Link>
          <Link to="/sources">Data sources</Link>
          <Link to="/analytics">Analytics</Link>
          {user?.role === "admin" && <Link to="/system">System health</Link>}
          <Link to="/settings">Settings</Link>
        </nav>
        <button className="btn" onClick={() => logout().catch((e) => toast(errText(e), "error"))}>Sign out</button>
        <div className="faint" style={{ fontSize: 11.5 }}>The facility registry and some wide tables are easier to use on a larger screen.</div>
      </div>
    </Shell>
  );
}

function DesktopPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Shell title={title} back>
      <div className="m-desktop-page"><Suspense fallback={<div className="page"><Skeleton lines={6} /></div>}>{children}</Suspense></div>
    </Shell>
  );
}

export default function MobileApp() {
  return (
    <Routes>
      <Route path="/map" element={<MapScreen />} />
      <Route path="/events" element={<EventsScreen />} />
      <Route path="/events/:ref" element={<EventScreen />} />
      <Route path="/alerts" element={<AlertsScreen />} />
      <Route path="/watchlist" element={<WatchlistScreen />} />
      <Route path="/watchlist/:id" element={<WatchlistEventsScreen />} />
      <Route path="/watchlists" element={<Navigate to="/watchlist" replace />} />
      <Route path="/more" element={<MoreScreen />} />
      <Route path="/overview" element={<DesktopPage title="Overview"><Overview /></DesktopPage>} />
      <Route path="/sources" element={<DesktopPage title="Data sources"><DataSources /></DesktopPage>} />
      <Route path="/system" element={<DesktopPage title="System health"><SystemHealth /></DesktopPage>} />
      <Route path="/analytics" element={<DesktopPage title="Analytics"><Analytics /></DesktopPage>} />
      <Route path="/settings" element={<DesktopPage title="Settings"><Settings /></DesktopPage>} />
      <Route path="*" element={<Navigate to="/map" replace />} />
    </Routes>
  );
}
