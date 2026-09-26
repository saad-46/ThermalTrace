/** Public landing page and sign-in. Everything numeric comes from GET /public/landing (live aggregates); when that
 *  fails the page says so instead of showing numbers. Sign-in and the Explore modes use the existing session flows
 *  (password login, server-enforced read-only demo sessions). */
import { useQuery } from "@tanstack/react-query";
import {
  Activity, ArrowRight, BellRing, BrainCircuit, ChevronDown, CircleCheck, CircleDashed, CircleDot, CircleX, CloudSun, Crosshair,
  Eye, Factory, FileUp, Flame, Gauge, GitMerge, KeyRound, Layers, Leaf, Lock, Map as MapIcon, MapPin, Satellite, ScrollText,
  Settings2, ShieldCheck, TriangleAlert, UserCheck, Waves,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Flame as FlameMark, IndiaOutline } from "../components/brand";
import { errText } from "../components/ui";
import { api } from "../lib/api";
import { relTime } from "../lib/format";
import { useMedia, useSession } from "../lib/session";
import type { DemoRole, PublicLanding, PublicSourceState } from "../lib/types";

const NUM = new Intl.NumberFormat("en-US");
const FLAME_CELLS = 3;

/** The busiest cells in distinct areas (at least 3 degrees apart), so adjacent hot cells do not stack flames. */
export function flameCells(cells: [number, number, number][]): [number, number, number][] {
  const out: [number, number, number][] = [];
  for (const c of cells) { // cells arrive sorted by count, busiest first
    if (out.every((o) => Math.hypot(o[0] - c[0], o[1] - c[1]) >= 3)) out.push(c);
    if (out.length === FLAME_CELLS) break;
  }
  return out;
}

// ---------------------------------------------------------------------------------------------- motion helpers
export function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** Adds `.in` when the element scrolls into view (fade-up). Without IntersectionObserver, or with reduced motion,
 *  content is shown immediately. */
function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined" || prefersReducedMotion()) {
      el.classList.add("in");
      return;
    }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        el.classList.add("in");
        io.disconnect();
      }
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return ref;
}

/** Counts up to `value` once visible; the exact value is always available to assistive technology. */
export function CountUp({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(() => (typeof IntersectionObserver === "undefined" || prefersReducedMotion() ? value : 0));
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined" || prefersReducedMotion()) {
      setShown(value);
      return;
    }
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const io = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      io.disconnect();
      const start = performance.now();
      const tick = (t: number) => {
        const p = Math.min(1, (t - start) / 900);
        setShown(Math.round(value * (1 - Math.pow(1 - p, 3))));
        if (p < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    }, { threshold: 0.3 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [value]);
  return (
    <span ref={ref} className="lp-count">
      <span aria-hidden>{NUM.format(shown)}</span>
      <span className="sr-only">{NUM.format(value)}</span>
    </span>
  );
}

function Section({ id, eyebrow, title, lead, children, className = "" }: {
  id: string; eyebrow: string; title: string; lead?: ReactNode; children: ReactNode; className?: string;
}) {
  const ref = useReveal<HTMLElement>();
  return (
    <section id={id} ref={ref} className={`lp-section reveal ${className}`} aria-labelledby={`${id}-title`}>
      <div className="lp-eyebrow">{eyebrow}</div>
      <h2 id={`${id}-title`}>{title}</h2>
      {lead && <p className="lp-lead">{lead}</p>}
      {children}
    </section>
  );
}

// ---------------------------------------------------------------------------------------------- live data
function useLanding() {
  return useQuery({
    queryKey: ["public-landing"],
    queryFn: () => api<PublicLanding>("/public/landing"),
    retry: 1,
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });
}

/** Real 30-day activity aggregated to a coarse grid, drawn on a plain graticule (no basemap, no individual events). */
export function ActivityMap({ data, loading }: { data: PublicLanding | undefined; loading: boolean }) {
  const cells = data?.activity.cells ?? [];
  // Beside the sign-in card on tablets the column is narrow and tall: use a portrait panel there.
  const portrait = useMedia("(min-width: 641px) and (max-width: 900px)");
  const view = useMemo(() => {
    if (!cells.length) return null;
    const lats = cells.map((c) => c[0]), lons = cells.map((c) => c[1]);
    const pad = 1.5;
    let s = Math.min(...lats) - pad, n = Math.max(...lats) + pad, w = Math.min(...lons) - pad, e = Math.max(...lons) + pad;
    const k = Math.cos((((s + n) / 2) * Math.PI) / 180); // equirectangular, scaled at mid-latitude
    // Fill a fixed panel aspect by widening the shorter axis (never by stretching the geography).
    const W = 640, H = portrait ? 800 : 360;
    const spanLon = (e - w) * k, spanLat = n - s;
    if (spanLon / spanLat < W / H) {
      const extra = ((spanLat * W) / H / k - (e - w)) / 2;
      w -= extra; e += extra;
    } else {
      const extra = ((spanLon * H) / W - spanLat) / 2;
      s -= extra; n += extra;
    }
    const x = (lon: number) => ((lon - w) / (e - w)) * W;
    const y = (lat: number) => ((n - lat) / (n - s)) * H;
    const max = Math.max(...cells.map((c) => c[2]));
    const step = 5;
    const meridians: number[] = [], parallels: number[] = [];
    for (let v = Math.ceil(w / step) * step; v <= e; v += step) meridians.push(v);
    for (let v = Math.ceil(s / step) * step; v <= n; v += step) parallels.push(v);
    return { W, H, x, y, max, meridians, parallels };
  }, [cells, portrait]);
  // SVG text scales with the viewBox: keep grid labels about 10 px on screen whatever the rendered width.
  const svgRef = useRef<SVGSVGElement>(null);
  const [labelSize, setLabelSize] = useState(10);
  useEffect(() => {
    const el = svgRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => { if (el.clientWidth) setLabelSize(Math.min(22, (10 * 640) / el.clientWidth)); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [view]);
  const total = cells.reduce((a, c) => a + c[2], 0);
  const days = data?.activity.window_days ?? 30;

  return (
    <figure className="lp-map glass" aria-busy={loading}>
      <figcaption className="lp-map-head">
        <span className="lp-map-title"><Activity size={14} aria-hidden /> Thermal activity · last {days} days</span>
        <span className="lp-map-meta">{view ? `${NUM.format(total)} events · ${cells.length} cells of ${data!.activity.cell_deg}°` : loading ? "Loading live data…" : "Live activity unavailable"}</span>
      </figcaption>
      {view ? (
        <svg ref={svgRef} viewBox={`0 0 ${view.W} ${view.H}`} className="lp-map-svg" role="img"
          aria-label={`Map of thermal event activity over the last ${days} days: ${NUM.format(total)} events in ${cells.length} one-degree grid cells. Larger, brighter circles mean more events; the busiest cells in ${flameCells(cells).length} distinct areas are marked with a flame.`}>
          <defs>
            <radialGradient id="lp-heat">
              <stop offset="0%" stopColor="#ffd08a" stopOpacity="0.95" />
              <stop offset="45%" stopColor="#ff7a2e" stopOpacity="0.75" />
              <stop offset="100%" stopColor="#ff4d1a" stopOpacity="0" />
            </radialGradient>
          </defs>
          <g className="lp-grid">
            {view.meridians.map((m) => <line key={`m${m}`} x1={view.x(m)} x2={view.x(m)} y1={0} y2={view.H} />)}
            {view.parallels.map((p) => <line key={`p${p}`} y1={view.y(p)} y2={view.y(p)} x1={0} x2={view.W} />)}
          </g>
          <g className="lp-grid-labels" aria-hidden style={{ fontSize: labelSize }}>
            {view.meridians.filter((m) => view.x(m) > 40 && view.x(m) < view.W - 40 && (labelSize < 14 || m % 10 === 0)).map((m) => <text key={`tm${m}`} x={view.x(m) + 3} y={view.H - labelSize * 0.6}>{m}°E</text>)}
            {view.parallels.filter((p) => view.y(p) > labelSize * 1.6 && view.y(p) < view.H - labelSize * 2 && (labelSize < 14 || p % 10 === 0)).map((p) => <text key={`tp${p}`} x={labelSize * 0.4} y={view.y(p) - labelSize * 0.4}>{p}°N</text>)}
          </g>
          <g>
            {[...cells].reverse().map(([lat, lon, cnt]) => {
              const r = 3 + 13 * Math.sqrt(cnt / view.max);
              return (
                <g key={`${lat},${lon}`} transform={`translate(${view.x(lon)} ${view.y(lat)})`}>
                  <circle r={Math.min(r * 1.9, 20)} fill="url(#lp-heat)" opacity={0.25 + 0.5 * Math.sqrt(cnt / view.max)} />
                  <circle r={Math.max(1.4, r * 0.28)} className="lp-core" />
                </g>
              );
            })}
          </g>
          <g className="lp-flames" aria-hidden>
            {/* The busiest cells (live data, largest first) are marked with a flame; its base sits on the cell centre. */}
            {flameCells(cells).map(([lat, lon, cnt]) => {
              const s = labelSize * 2 + 10 * Math.sqrt(cnt / view.max);
              return (
                <g key={`f${lat},${lon}`} transform={`translate(${view.x(lon) - s / 2} ${view.y(lat) - s * 0.95})`}>
                  <g className="lp-flame"><FlameMark size={s} /></g>
                </g>
              );
            })}
          </g>
        </svg>
      ) : (
        <div className="lp-map-empty" role="status">
          {loading ? <span className="spinner" /> : <><Crosshair size={16} aria-hidden /> Live activity is unavailable right now. No placeholder data is shown.</>}
        </div>
      )}
      <div className="lp-map-foot">Aggregated NASA FIRMS events on a 1° grid; flames mark the busiest areas. Circles show where activity was detected, not what caused it.</div>
    </figure>
  );
}

// ---------------------------------------------------------------------------------------------- sign-in
const EXPLORE: { role: DemoRole; title: string; text: string; icon: ReactNode }[] = [
  { role: "analyst", title: "Explore as Analyst", icon: <Crosshair size={18} aria-hidden />,
    text: "Investigate a real thermal event and learn how ThermalTrace builds evidence." },
  { role: "admin", title: "Explore as Admin", icon: <Settings2 size={18} aria-hidden />,
    text: "Explore ingestion, data sources, workers, models, alerts and system governance." },
];

function useExplore() {
  const { startDemo } = useSession();
  const config = useQuery({ queryKey: ["explore-config"], queryFn: () => api<{ enabled: boolean }>("/auth/demo"), retry: false, staleTime: 60_000 });
  const [busy, setBusy] = useState<DemoRole | null>(null);
  const [error, setError] = useState<string | null>(null);
  const start = async (role: DemoRole) => {
    setBusy(role);
    setError(null);
    try {
      await startDemo(role);
    } catch (err) {
      setError(errText(err));
      setBusy(null);
    }
  };
  return { enabled: !!config.data?.enabled, busy, error, start };
}

function AuthPanel({ explore }: { explore: ReturnType<typeof useExplore> }) {
  const { login } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside id="signin" className="lp-auth glass" aria-label="Sign in and explore">
      <form className="lp-auth-form" onSubmit={submit} aria-labelledby="signin-title">
        <h2 id="signin-title">Sign in</h2>
        <p className="lp-auth-sub">Accounts are issued by an administrator.</p>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input id="password" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && <div role="alert" className="lp-error">{error}</div>}
        <button className="btn primary lp-signin" type="submit" disabled={busy}>
          {busy && <span className="spinner" />} Sign in
        </button>
      </form>

      {explore.enabled && (
        <section className="lp-explore" aria-labelledby="explore-title">
          <div className="lp-or" aria-hidden><span>or</span></div>
          <h3 id="explore-title">Explore without an account</h3>
          <div className="lp-explore-list">
            {EXPLORE.map((o) => (
              <button key={o.role} type="button" className="lp-explore-btn" onClick={() => explore.start(o.role)}
                disabled={explore.busy !== null} aria-busy={explore.busy === o.role}
                aria-label={o.title} aria-describedby={`explore-${o.role}-text`}>
                <span className="lp-explore-icon">{explore.busy === o.role ? <span className="spinner" /> : o.icon}</span>
                <span className="lp-explore-body">
                  <span className="lp-explore-title">{o.title}</span>
                  <span id={`explore-${o.role}-text`} className="lp-explore-text">{o.text}</span>
                </span>
                <ArrowRight size={15} className="lp-explore-arrow" aria-hidden />
              </button>
            ))}
          </div>
          <p className="lp-auth-note"><Lock size={12} aria-hidden /> Read-only guided session on the live system. Changes are refused by the server.</p>
          {explore.error && <div role="alert" className="lp-error">{explore.error}</div>}
        </section>
      )}
    </aside>
  );
}

// ---------------------------------------------------------------------------------------------- sections
export function LiveStatus({ data, error }: { data: PublicLanding | undefined; error: boolean }) {
  if (error) return <div className="lp-live off" role="status"><CircleDot size={12} aria-hidden /> Live status unavailable</div>;
  if (!data) return <div className="lp-live" role="status"><span className="lp-dot pending" aria-hidden /> Connecting to live data…</div>;
  return (
    <div className="lp-live" role="status">
      <span className="lp-dot" aria-hidden /> Live thermal intelligence
      <span className="lp-live-sep" aria-hidden>·</span>
      <span className="lp-live-detail">latest detection {relTime(data.latest_detection)}</span>
    </div>
  );
}

/** "N / M sources active", expandable to every source's backend state and what an inactive one needs. */
export function SourceHealth({ data }: { data: PublicLanding }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    popRef.current?.scrollIntoView?.({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onDown = (e: PointerEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("pointerdown", onDown); };
  }, [open]);
  const order = (s: PublicLanding["sources"][number]) => (s.state === "active" ? 0 : 1);
  const sorted = [...data.sources].sort((a, b) => order(a) - order(b));
  return (
    <div className="lp-health" ref={ref}>
      <button type="button" className="lp-health-btn" aria-expanded={open} aria-controls="source-health" onClick={() => setOpen((o) => !o)}>
        <span className="num">{data.sources_active} / {data.sources_total}</span> sources active
        <ChevronDown size={14} aria-hidden className={open ? "open" : ""} />
      </button>
      {open && (
        <div id="source-health" ref={popRef} className="lp-health-pop glass" role="region" aria-label="Data source health">
          <div className="lp-health-head">
            <span>Data sources <span className="lp-health-when">as of {relTime(data.generated_at)}</span></span>
            <button type="button" className="lp-health-close" onClick={() => setOpen(false)} aria-label="Close data source health">×</button>
          </div>
          <ul>
            {sorted.map((s) => (
              <li key={s.id} className={`st-${s.state}`}>
                <span className="lp-health-name">{s.name}</span>
                <StateBadge state={s.state} />
                {s.state !== "active" && <span className="lp-health-why">{s.requirement ? `Needs ${s.requirement}` : s.reason}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function Snapshot({ data, loading, error }: { data: PublicLanding | undefined; loading: boolean; error: boolean }) {
  const cards: { icon: ReactNode; label: string; value: (d: PublicLanding) => number; note: (d: PublicLanding) => string }[] = [
    { icon: <Satellite size={17} />, label: "Thermal detections", value: (d) => d.counts.detections, note: () => "NASA FIRMS pixels ingested" },
    { icon: <Flame size={17} />, label: "Thermal events", value: (d) => d.counts.events, note: () => "Detections clustered for investigation" },
    { icon: <Activity size={17} />, label: "Events, last 30 days", value: (d) => d.counts.events_recent, note: (d) => `Latest detection ${relTime(d.latest_detection)}` },
    { icon: <Factory size={17} />, label: "Mapped facilities", value: (d) => d.counts.facilities, note: () => "Available for spatial attribution" },
    { icon: <Layers size={17} />, label: "Data sources active", value: (d) => d.sources_active, note: (d) => `of ${d.sources_total} integrated sources` },
  ];
  return (
    <Section id="snapshot" eyebrow="Live system snapshot" title="The system, as it is right now.">
      {error ? (
        <p className="lp-unavailable" role="status">Live statistics unavailable. No figures are shown rather than estimates.</p>
      ) : (
        <>
          <div className="lp-stats" aria-busy={loading}>
            {cards.map((c) => (
              <div key={c.label} className="lp-stat glass">
                <span className="lp-stat-icon" aria-hidden>{c.icon}</span>
                <div className="lp-stat-value">{data ? <CountUp value={c.value(data)} /> : <span className="lp-skel" aria-label="Loading" />}</div>
                <div className="lp-stat-label">{c.label}</div>
                <div className="lp-stat-note">{data ? c.note(data) : " "}</div>
              </div>
            ))}
          </div>
          {data && (
            <div className="lp-system">
              <span className={`lp-sys ${data.workers_online ? "ok" : "warn"}`}>
                {data.workers_online ? <ShieldCheck size={14} aria-hidden /> : <Gauge size={14} aria-hidden />}
                Processing {data.workers_online ? "online" : "paused or offline"}
              </span>
              <SourceHealth data={data} />
              <span>FIRMS synced {relTime(data.firms_last_sync)}</span>
              <span>Classifier of record: <code>{data.classifier}</code></span>
              <span className="faint">Figures refresh every {Math.round(data.cache_seconds / 60)} min</span>
            </div>
          )}
        </>
      )}
    </Section>
  );
}

const STAGES = [
  { n: "01", title: "Detect", text: "NASA FIRMS identifies thermal anomalies from MODIS and VIIRS satellite passes.",
    more: "Detections are ingested on a schedule, normalised and de-duplicated; each keeps its raw values and source." },
  { n: "02", title: "Enrich", text: "Detections are combined with facilities, land cover, weather and geospatial context.",
    more: "OpenStreetMap, WRI, Global Energy Monitor, ESA WorldCover, Sentinel-2 and Open-Meteo; each lookup records its status." },
  { n: "03", title: "Correlate", text: "Thermal activity is grouped into events and related to nearby infrastructure.",
    more: "Spatio-temporal clustering, persistence over days, and facility attribution within 2 km and 10 km." },
  { n: "04", title: "Explain", text: "Persistence, FRP, brightness, land cover and spectral change are combined and explained.",
    more: "The classifier of record assigns one of eight classes with the evidence behind it; weak evidence stays INSUFFICIENT EVIDENCE instead of a forced guess." },
  { n: "05", title: "Review", text: "Analysts receive a prioritised, auditable investigation rather than an unexplained prediction.",
    more: "Confirm, reclassify or reject with notes; decisions are audited and become training labels." },
];

function Workflow() {
  return (
    <Section id="how" eyebrow="How ThermalTrace works" title="From detection to decision."
      lead="Five stages turn a hot pixel into an investigation an analyst can check and defend.">
      <ol className="lp-flow">
        {STAGES.map((s) => (
          <li key={s.n} className="lp-stage glass" tabIndex={0}>
            <span className="lp-stage-n">{s.n}</span>
            <h3>{s.title}</h3>
            <p>{s.text}</p>
            <p className="lp-stage-more">{s.more}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}

const CAPABILITIES = [
  { icon: <MapIcon size={18} />, title: "GIS intelligence", text: "Interactive spatial investigation using thermal detections and infrastructure context." },
  { icon: <GitMerge size={18} />, title: "Evidence fusion", text: "Combines independent evidence sources into a single investigation." },
  { icon: <Factory size={18} />, title: "Facility attribution", text: "Distance-decay and facility context as supporting evidence, not proof." },
  { icon: <Leaf size={18} />, title: "Land cover", text: "ESA WorldCover shows the environmental context around each event." },
  { icon: <Waves size={18} />, title: "Spectral change", text: "Sentinel-2 NDVI and NBR before/after analysis when suitable clear imagery exists." },
  { icon: <BrainCircuit size={18} />, title: "Explainable decisions", text: "Rule traces, and SHAP for trained models, show contributing factors instead of a black box." },
  { icon: <UserCheck size={18} />, title: "Human review", text: "Analysts review, annotate, reclassify and confirm; nothing is confirmed by the model alone." },
  { icon: <BellRing size={18} />, title: "Alerts & watchlists", text: "Monitor places, facilities and conditions with cooldowns and a recorded delivery history." },
];

function Capabilities() {
  return (
    <Section id="capabilities" eyebrow="Capabilities" title="One investigation. Multiple evidence layers.">
      <div className="lp-cards">
        {CAPABILITIES.map((c) => (
          <div key={c.title} className="lp-card glass">
            <span className="lp-card-icon" aria-hidden>{c.icon}</span>
            <h3>{c.title}</h3>
            <p>{c.text}</p>
          </div>
        ))}
      </div>
    </Section>
  );
}

const TRAIL = ["Satellite detection", "Event clustering", "Facility proximity", "Persistence", "Land cover", "Spectral change",
  "Classification", "Explanation (rules / SHAP)", "Human review", "Current status"];

function EvidenceTrail() {
  return (
    <Section id="evidence" eyebrow="How ThermalTrace thinks" title="Every event has an evidence trail.">
      <div className="lp-split-grid">
      <div className="lp-split-body">
        <p className="lp-lead">
          Each event page walks through how the assessment was reached. Every stage shows whether its evidence is available,
          where it came from, when it was retrieved and what it contributes.
        </p>
        <ul className="lp-points">
          <li>Missing evidence is shown as missing, never as negative evidence.</li>
          <li>Confidence indicates the strength of available supporting evidence; it is not proof and not a probability of fire.</li>
          <li>An event is confirmed only after imagery confirmation or analyst review.</li>
        </ul>
      </div>
      <ol className="lp-trail glass" aria-label="Evidence trail stages">
        {TRAIL.map((t, i) => <li key={t}><span className="lp-trail-n" aria-hidden>{String(i + 1).padStart(2, "0")}</span>{t}</li>)}
      </ol>
      </div>
    </Section>
  );
}

/** What each integrated source contributes; states come from the live source registry. */
const SOURCE_ROLE: Record<string, string> = {
  firms: "Thermal detections (MODIS, VIIRS)",
  osm: "Industrial sites and land use",
  wri_gppd: "Global power-plant database",
  gem: "Coal plants, mines and steel trackers",
  cea: "Indian power-station registry (file import)",
  esa_worldcover: "10 m land cover, 2021",
  earth_search: "Sentinel-2 L2A scene search and NDVI/NBR change",
  cdse: "Sentinel-2 SWIR composites for visual review of an event",
  open_meteo: "Weather at detection time",
  geonames: "Place names",
  nominatim: "Reverse geocoding",
};

export const SOURCE_STATE: Record<PublicSourceState, { label: string; icon: ReactNode }> = {
  active: { label: "Active", icon: <CircleCheck size={13} aria-hidden /> },
  degraded: { label: "Degraded", icon: <TriangleAlert size={13} aria-hidden /> },
  unavailable: { label: "Unavailable", icon: <CircleX size={13} aria-hidden /> },
  credentials_required: { label: "Credentials required", icon: <KeyRound size={13} aria-hidden /> },
  import_required: { label: "Import required", icon: <FileUp size={13} aria-hidden /> },
  not_used: { label: "Not currently used", icon: <CircleDashed size={13} aria-hidden /> },
};

function StateBadge({ state }: { state: PublicSourceState }) {
  const m = SOURCE_STATE[state];
  return <span className={`lp-state ${state}`}>{m.icon}{m.label}</span>;
}

const KIND_ICON: Record<string, ReactNode> = {
  detections: <Flame size={17} />, facilities: <Factory size={17} />, imagery: <Satellite size={17} />,
  landcover: <Leaf size={17} />, weather: <CloudSun size={17} />, geocoding: <MapPin size={17} />,
};

export function Sources({ data, error }: { data: PublicLanding | undefined; error: boolean }) {
  return (
    <Section id="data" eyebrow="Data" title="Built on real-world data."
      lead="Every figure and every piece of evidence traces back to a named, licensed source. Status is read from the live source registry.">
      {error && <p className="lp-unavailable" role="status">Source status is unavailable right now.</p>}
      {!error && !data && <p className="lp-unavailable" role="status"><span className="spinner" /> Loading source status…</p>}
      {data && (
        <ul className="lp-sources">
          {data.sources.map((s) => (
            <li key={s.id} className={`lp-source glass st-${s.state}`}>
              <div className="lp-source-head">
                <span className={`lp-source-icon${s.id === "cdse" ? " india" : ""}`} aria-hidden>
                  {s.id === "cdse" ? <IndiaOutline size={24} /> : KIND_ICON[s.kind] ?? <Layers size={17} />}
                </span>
                <div className="lp-source-title">
                  <div className="lp-source-name">{s.name}</div>
                  <div className="lp-source-role">{SOURCE_ROLE[s.id] ?? s.kind}</div>
                </div>
              </div>
              <div className="lp-source-foot">
                <StateBadge state={s.state} />
                {s.state === "active"
                  ? s.last_success_at && <span className="lp-source-meta">verified {relTime(s.last_success_at)}</span>
                  : s.requirement && <span className="lp-source-meta">Needs {s.requirement}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

const TECH = [
  { name: "NASA FIRMS", role: "Active-fire detections" },
  { name: "PostgreSQL + PostGIS", role: "Spatial storage, indexing and queries" },
  { name: "FastAPI", role: "API, workers and job queue" },
  { name: "React + TypeScript", role: "Web and mobile client (PWA)" },
  { name: "MapLibre GL", role: "Interactive maps" },
  { name: "Rule cascade", role: "Documented classifier of record" },
  { name: "LightGBM", role: "Trainable model; active only if an administrator activates it" },
  { name: "SHAP", role: "Per-feature explanations for trained models" },
  { name: "ESA WorldCover", role: "Land-cover context via rasterio" },
  { name: "Sentinel-2", role: "NDVI / NBR spectral change" },
];

function Tech() {
  return (
    <Section id="tech" eyebrow="Technology" title="Built for real-world geospatial intelligence.">
      <ul className="lp-tech">
        {TECH.map((t) => <li key={t.name} className="glass"><strong>{t.name}</strong><span>{t.role}</span></li>)}
      </ul>
    </Section>
  );
}

const TRUST = [
  { icon: <ScrollText size={16} />, text: "Evidence is traceable to its source and retrieval time" },
  { icon: <UserCheck size={16} />, text: "Human review remains part of the workflow" },
  { icon: <Eye size={16} />, text: "Missing evidence is shown as missing" },
  { icon: <Gauge size={16} />, text: "Confidence is supporting evidence, not proof" },
  { icon: <Lock size={16} />, text: "Demo sessions are read-only, enforced by the server" },
  { icon: <ShieldCheck size={16} />, text: "Administrative actions are audited" },
  { icon: <Settings2 size={16} />, text: "Model activation is a governed, audited decision" },
  { icon: <Activity size={16} />, text: "Data-source status is visible to every user" },
];

function Trust() {
  return (
    <Section id="trust" eyebrow="Accountability" title="Designed for accountable decisions.">
      <ul className="lp-trust">
        {TRUST.map((t) => <li key={t.text}><span aria-hidden>{t.icon}</span>{t.text}</li>)}
      </ul>
    </Section>
  );
}

function FinalCta({ explore }: { explore: ReturnType<typeof useExplore> }) {
  const ref = useReveal<HTMLElement>();
  return (
    <section ref={ref} className="lp-cta glass reveal" aria-labelledby="cta-title">
      <h2 id="cta-title">Explore ThermalTrace.</h2>
      <p>Sign in with your account, or walk through the live system with a guided, read-only tour.</p>
      <div className="lp-cta-actions">
        <a className="btn primary" href="#signin" onClick={() => setTimeout(() => document.getElementById("email")?.focus(), 350)}>Sign in</a>
        {explore.enabled && EXPLORE.map((o) => (
          <button key={o.role} type="button" className="btn" onClick={() => explore.start(o.role)} disabled={explore.busy !== null}>
            Start the {o.role} tour
          </button>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------------------------- page
export default function Landing() {
  const landing = useLanding();
  const explore = useExplore();
  const data = landing.data;
  const error = landing.isError && !data;
  return (
    <div className="landing">
      <a className="lp-skip" href="#signin">Skip to sign in</a>
      <div className="lp-bg" aria-hidden />
      <header className="lp-nav">
        <span className="lp-logo"><span className="brand-mark" aria-hidden /> ThermalTrace</span>
        <nav aria-label="Page sections" className="lp-links">
          <a href="#how">How it works</a>
          <a href="#capabilities">Capabilities</a>
          <a href="#data">Data</a>
          <a href="#signin" className="lp-link-cta">Sign in</a>
        </nav>
      </header>
      <main>
        <section className="lp-hero" aria-labelledby="lp-title">
          <div className="lp-hero-copy">
            <LiveStatus data={data} error={error} />
            <h1 id="lp-title">
              <span className="lp-wordmark">ThermalTrace</span>
              <span className="lp-slogan">From heat signals to actionable intelligence.</span>
            </h1>
            <p className="lp-intro">
              ThermalTrace combines satellite thermal detections, geospatial infrastructure, environmental context and
              explainable evidence to help analysts understand what is happening on the ground.
            </p>
          </div>
          <AuthPanel explore={explore} />
          <div className="lp-hero-visual"><ActivityMap data={data} loading={landing.isLoading} /></div>
        </section>
        <Snapshot data={data} loading={landing.isLoading} error={error} />
        <Workflow />
        <Capabilities />
        <EvidenceTrail />
        <Sources data={data} error={error} />
        <Tech />
        <Trust />
        <FinalCta explore={explore} />
      </main>
      <footer className="lp-footer">
        <div>
          <span className="lp-logo"><span className="brand-mark" aria-hidden /> ThermalTrace</span>
          <p>Geospatial intelligence for understanding thermal events.</p>
        </div>
        <p className="lp-credit">Built with <span className="lp-heart" role="img" aria-label="love">♥</span> by CodeCrafters</p>
      </footer>
    </div>
  );
}
