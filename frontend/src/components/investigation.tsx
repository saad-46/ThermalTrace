import { Bell, Eye, FileText, RefreshCw } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { fetchImage } from "../lib/api";
import { compass, coordsLabel, fmtDateTime, fmtNum, locationLabel, relTime, titleCase } from "../lib/format";
import { actions, useAction, useReports, useSimilar, useWatchlists } from "../lib/hooks";
import { useSession } from "../lib/session";
import { CLASS_META, CLASS_ORDER, CONFIDENCE_EXPLAINER, FP_REASONS, confidenceNote } from "../lib/taxonomy";
import type { EventDetail, Scene } from "../lib/types";
import {
  AnswerGrid, ConfidenceBreakdown, EventRowMini, EvidenceList, EvidenceMatrix, ExtLink, FacilityList, Fingerprint, ModelPanel,
  PersistencePanel, Provenance, Timeline,
} from "./evidence";
import { ActionButton, errorText, EvidenceState, pendingLabel, stepPhase, useRequestBlocker, useRequestSteps } from "./enrichment";
import { LandCoverPanel, SpectralChangePanel } from "./landcover";
import { EvidenceChain, PriorityPanel, PriorityPill } from "./triage";
import { ClassLabel, errText, ModePill, StatePill, useToast } from "./ui";
import { downloadFile } from "../lib/api";

// ------------------------------------------------------------------ satellite
function SceneMeta({ s }: { s: Scene }) {
  return (
    <div className="faint" style={{ fontSize: 11.5 }}>
      {fmtDateTime(s.acquired_at)} · {s.platform ?? "Sentinel-2"} · {s.processing_level ?? "L2A"} · {s.cloud_cover == null ? "cloud n/a" : `${fmtNum(s.cloud_cover, 0)}% cloud`} · Copernicus via {s.provider}
    </div>
  );
}

export function SatellitePanel({ ev }: { ev: EventDetail }) {
  const scenes = ev.satellite;
  const byRel = useMemo(() => ({
    before: scenes.filter((s) => s.relation === "before").sort((a, b) => (a.acquired_at < b.acquired_at ? 1 : -1))[0],
    after: [...scenes].filter((s) => s.relation !== "before").sort((a, b) => (a.acquired_at < b.acquired_at ? 1 : -1))[0],
  }), [scenes]);
  const [left, setLeft] = useState<Scene | undefined>(byRel.before);
  const [right, setRight] = useState<Scene | undefined>(byRel.after ?? scenes[scenes.length - 1]);
  const [split, setSplit] = useState(50);
  const [swir, setSwir] = useState<{ url?: string; error?: string; loading?: boolean }>({});
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { setLeft(byRel.before); setRight(byRel.after ?? scenes[scenes.length - 1]); setSwir({}); }, [ev.id, byRel, scenes]);
  const { phase, state, job } = stepPhase(ev, "satellite");
  const req = useRequestSteps(ev, ["satellite"]);
  const demo = useRequestBlocker();
  const search = (label: string) => (
    <ActionButton onClick={req.run} busy={req.sending || phase === "pending"} busyLabel="Searching…" testId="satellite-search">{label}</ActionButton>
  );
  const meaning = "Scenes let an analyst check land cover, cloud and visible change around the event. Imagery confirmation requires actual imagery of the event; a scene list alone confirms nothing.";
  const window = state?.window_start ? `${fmtDateTime(state.window_start)} → ${fmtDateTime(state.window_end ?? state.at)}` : null;

  if (!scenes.length || phase === "pending") {
    if (phase === "pending")
      return <EvidenceState tone="busy" title="Searching Sentinel-2 imagery…" testId="satellite-state">Querying the Sentinel-2 L2A catalogue for scenes covering the event location; {pendingLabel(job)}.</EvidenceState>;
    if (phase === "failed")
      return (
        <EvidenceState tone="warn" title="Sentinel-2 search failed" testId="satellite-state" action={search("Search again")}>
          The catalogue request ({relTime(state?.at)}) did not complete: {errorText(state?.category)}. This is a provider failure, not an absence of imagery. Details are in the server logs.
        </EvidenceState>
      );
    if (phase === "job_failed")
      return (
        <EvidenceState tone="warn" title="Imagery search did not complete" testId="satellite-state" action={search("Search again")}>
          The background job stopped with an error{job?.error_type ? ` (${job.error_type})` : ""}. Nothing was stored.
        </EvidenceState>
      );
    if (phase === "ok")
      return (
        <EvidenceState title="No suitable Sentinel-2 scene was available for this event" testId="satellite-state" action={search("Search again")} meaning={meaning}>
          The catalogue answered with no L2A scene covering the event with cloud ≤ {state?.max_cloud ?? 60}%{window ? ` between ${window}` : ""}. Searched {relTime(state?.at)}.
        </EvidenceState>
      );
    return (
      <EvidenceState title="Imagery has not been searched yet" testId="satellite-state" action={search("Search Sentinel-2 imagery")} meaning={meaning}>
        Search the Sentinel-2 L2A catalogue (Element84 Earth Search, public, no key required) for scenes whose footprint contains the event, from 45 days before the first detection until now, with cloud ≤ 60%.
      </EvidenceState>
    );
  }
  const move = (e: PointerEvent) => {
    if (!box.current || e.buttons !== 1) return;
    const r = box.current.getBoundingClientRect();
    setSplit(Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100)));
  };
  const loadSwir = async (s: Scene) => {
    setSwir({ loading: true });
    try { setSwir({ url: await fetchImage(`/satellite/${s.id}/swir.png`) }); } catch (e) { setSwir({ error: errText(e) }); }
  };
  const pick = (s: Scene) => (s.relation === "before" ? setLeft(s) : setRight(s));
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="faint" style={{ fontSize: 12 }}>
        Provider previews show the full ~110 km tile, not a zoom on the event. Use them to check land cover and cloud, not to confirm a fire. The event is at {ev.latitude.toFixed(4)}, {ev.longitude.toFixed(4)}.
      </div>
      {left && right && left.id !== right.id ? (
        <div ref={box} className="compare" style={{ ["--split" as string]: `${split}%` }} onPointerDown={move} onPointerMove={move}
          role="slider" aria-label="Before/after comparison" aria-valuenow={Math.round(split)} aria-valuemin={0} aria-valuemax={100} tabIndex={0}
          onKeyDown={(e) => { if (e.key === "ArrowLeft") setSplit((v) => Math.max(0, v - 5)); if (e.key === "ArrowRight") setSplit((v) => Math.min(100, v + 5)); }}>
          {right.thumbnail_url && <img src={right.thumbnail_url} alt={`Sentinel-2 ${right.relation} ${right.acquired_at}`} />}
          {left.thumbnail_url && <img className="top" src={left.thumbnail_url} alt={`Sentinel-2 ${left.relation} ${left.acquired_at}`} />}
          <div className="handle" />
          <span className="lbl" style={{ left: 6 }}>{left.relation} · {left.acquired_at.slice(0, 10)}</span>
          <span className="lbl" style={{ right: 6 }}>{right.relation} · {right.acquired_at.slice(0, 10)}</span>
        </div>
      ) : (
        <div className="compare">{(right ?? left)?.thumbnail_url && <img src={(right ?? left)!.thumbnail_url!} alt="Sentinel-2 preview" />}</div>
      )}
      {left && <div><b style={{ fontSize: 12 }}>Left:</b> <SceneMeta s={left} /></div>}
      {right && <div><b style={{ fontSize: 12 }}>Right:</b> <SceneMeta s={right} /></div>}
      <div className="scene-strip" role="list">
        {scenes.map((s) => (
          <button key={s.id} role="listitem" className={`scene ${s.id === left?.id || s.id === right?.id ? "on" : ""}`} onClick={() => pick(s)} title={`${s.item_id}`}>
            {s.thumbnail_url ? <img src={s.thumbnail_url} alt="" loading="lazy" /> : <div style={{ height: 70 }} />}
            <div className="cap">{s.relation} · {s.acquired_at.slice(5, 10)}<br />{fmtNum(s.cloud_cover, 0)}% cloud</div>
          </button>
        ))}
      </div>
      <div className="row wrap">
        {right?.item_url && <ExtLink href={right.item_url}>STAC item</ExtLink>}
        <button className="btn sm" onClick={() => right && loadSwir(right)} disabled={!right || swir.loading || !!demo}
          title={demo ? "SWIR renders use a limited Copernicus quota and are disabled in the read-only demo" : "Renders via Copernicus Data Space (OAuth, server-side)"}>
          {swir.loading ? <span className="spinner" /> : null} Render SWIR (B12/B8A/B4) around event
        </button>
      </div>
      {swir.error && <div className="faint" style={{ fontSize: 12 }}>SWIR render unavailable: {swir.error}</div>}
      <div className="faint" style={{ fontSize: 11.5 }} data-testid="satellite-search-info">
        {state ? <>Searched {relTime(state.at)}: {state.scenes ?? scenes.length} scene(s) with cloud ≤ {state.max_cloud ?? 60}%{window ? `, ${window}` : ""}. </> : null}
        {state && ev.last_detected > (state.window_end ?? state.at) ? <b>The event has new detections since this search; search again for newer scenes. </b> : null}
        Scenes: Copernicus Sentinel-2 L2A via Element84 Earth Search.
      </div>
      {!demo && <div>{search("Search again")}</div>}
      {swir.url && <img src={swir.url} alt="SWIR composite around event" style={{ width: "100%", borderRadius: 6 }} />}
    </div>
  );
}

// ------------------------------------------------------------------ weather
const WEATHER_MEANING = "Wind, temperature and precipitation provide supporting environmental context for this event. Weather does not show what caused a fire.";

export function WeatherPanel({ ev }: { ev: EventDetail }) {
  const w = ev.weather[0];
  const { phase, state, job } = stepPhase(ev, "weather");
  const req = useRequestSteps(ev, ["weather"]);
  const when = `the last detection (${fmtDateTime(ev.last_detected)})`;
  const button = (label: string) => (
    <ActionButton onClick={req.run} busy={req.sending || phase === "pending"} busyLabel="Retrieving weather…" testId="weather-request">{label}</ActionButton>
  );
  if (!w || phase === "pending") {
    if (phase === "pending")
      return <EvidenceState tone="busy" title="Retrieving weather…" testId="weather-state">Open-Meteo is queried for the event location at {when}; {pendingLabel(job)}.</EvidenceState>;
    if (phase === "failed")
      return (
        <EvidenceState tone="warn" title="Weather service temporarily unavailable" testId="weather-state" action={button("Try again")} meaning={WEATHER_MEANING}>
          The last request ({relTime(state?.at)}) did not complete: {errorText(state?.category)}. This is a provider failure, not an absence of weather data. Details are in the server logs.
        </EvidenceState>
      );
    if (phase === "job_failed")
      return (
        <EvidenceState tone="warn" title="Weather retrieval did not complete" testId="weather-state" action={button("Try again")}>
          The background job stopped with an error{job?.error_type ? ` (${job.error_type})` : ""} before the provider answered. Nothing was stored.
        </EvidenceState>
      );
    if (phase === "no_data")
      return (
        <EvidenceState title="No weather observation available for this event" testId="weather-state" action={button("Retrieve again")} meaning={WEATHER_MEANING}>
          Open-Meteo answered, but has no values for the hour of {when} at this location ({state?.detail}). Recent reanalysis can lag by several days.
        </EvidenceState>
      );
    return (
      <EvidenceState title="Weather context unavailable" testId="weather-state" action={button("Retrieve weather")} meaning={WEATHER_MEANING}>
        This event has not been enriched with weather data yet. Retrieve weather to add environmental context around {when}: temperature, humidity, wind, precipitation and pressure from Open-Meteo (ERA5 reanalysis or the recent hourly model; no key required).
      </EvidenceState>
    );
  }
  const disp = w.wind_direction_deg == null ? null : (w.wind_direction_deg + 180) % 360;
  // only what the provider returned: a missing value is left out, never shown as zero
  const rows: [string, ReactNode, boolean][] = [
    ["Condition", w.condition, w.condition != null],
    ["Temperature", `${fmtNum(w.temperature_c)} °C`, w.temperature_c != null],
    ["Humidity", `${fmtNum(w.humidity_pct, 0)} %`, w.humidity_pct != null],
    ["Wind", `${fmtNum(w.wind_speed_ms)} m/s${w.wind_direction_deg != null ? ` from ${compass(w.wind_direction_deg)} (${fmtNum(w.wind_direction_deg, 0)}°)` : ""}`, w.wind_speed_ms != null],
    ["Precipitation", `${fmtNum(w.precipitation_mm)} mm`, w.precipitation_mm != null],
    ["Pressure", `${fmtNum(w.pressure_hpa, 0)} hPa`, w.pressure_hpa != null],
    ["Potential dispersion", disp == null ? null : `toward ${compass(disp)} (${disp.toFixed(0)}°)`, disp != null],
  ];
  return (
    <div className="row" style={{ alignItems: "flex-start", gap: 16, flexWrap: "wrap" }} data-testid="weather-result">
      <div className="faint" style={{ fontSize: 12, width: "100%" }}><b>Weather context</b> at the event location, nearest hour to {when}. {WEATHER_MEANING}</div>
      <svg width="110" height="110" viewBox="-55 -55 110 110" role="img" aria-label={`Potential dispersion toward ${compass(disp)}`}>
        <circle r="46" fill="none" stroke="var(--border-strong)" />
        {["N", "E", "S", "W"].map((c, i) => <text key={c} x={Math.sin((i * Math.PI) / 2) * 38} y={-Math.cos((i * Math.PI) / 2) * 38 + 4} fontSize="10" textAnchor="middle" fill="var(--text-3)">{c}</text>)}
        {disp != null && (
          <g transform={`rotate(${disp})`}>
            <line x1="0" y1="18" x2="0" y2="-30" stroke="var(--info)" strokeWidth="2.5" strokeLinecap="round" />
            <path d="M -6 -22 L 0 -34 L 6 -22" fill="none" stroke="var(--info)" strokeWidth="2.5" strokeLinejoin="round" />
          </g>
        )}
        <circle r="3" fill="var(--thermal)" />
      </svg>
      <dl className="kv" style={{ flex: 1, minWidth: 200 }}>
        <dt>Observed</dt><dd>{fmtDateTime(w.observed_at)}</dd>
        {rows.filter(([, , ok]) => ok).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd className="num">{v}</dd></Fragment>)}
        <dt>Source</dt><dd className="faint">{w.dataset} · retrieved {relTime(w.retrieved_at)}</dd>
      </dl>
      <div className="faint" style={{ fontSize: 11.5, width: "100%" }}>
        The dispersion direction is inferred from the wind vector only. It is not plume tracking and does not show where smoke actually went.
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ analyst workflow
export function ReviewPanel({ ev, onChanged }: { ev: EventDetail; onChanged?: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const [decision, setDecision] = useState<string>("confirm");
  const [cls, setCls] = useState<string>(ev.classification ?? "unknown");
  const [reason, setReason] = useState<string>("industrial_process_heat");
  const [notes, setNotes] = useState("");
  const [note, setNote] = useState("");
  const [url, setUrl] = useState("");
  const inv = [["event", ev.public_id], ["events"], ["alerts"]];
  const review = useAction(actions.review(ev.public_id), inv);
  const addNote = useAction(actions.note(ev.public_id), inv);
  const analyst = can("analyst");

  const submit = async () => {
    const body: Record<string, unknown> = { decision, notes: notes || undefined };
    if (decision === "reclassify") body.source_class = cls;
    if (decision === "false_positive") body.false_positive_reason = reason;
    try {
      await review.mutateAsync(body);
      toast(`Decision recorded: ${titleCase(decision)}`);
      setNotes("");
      onChanged?.();
    } catch (e) { toast(errText(e), "error"); }
  };
  const submitNote = async () => {
    try {
      await addNote.mutateAsync({ body: note, url: url || undefined });
      toast("Note added");
      setNote(""); setUrl("");
    } catch (e) { toast(errText(e), "error"); }
  };

  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="row wrap">
        <span className="muted">Current status</span> <StatePill state={ev.display_state} />
        {ev.investigation && <span className="faint">Investigation {ev.investigation.status}{ev.investigation.assignee ? ` · ${ev.investigation.assignee}` : ""}</span>}
      </div>
      {analyst ? (
        <div className="stack" style={{ gap: 8 }}>
          <div className="field">
            <label htmlFor="decision">Decision</label>
            <div className="seg" role="radiogroup" id="decision" style={{ flexWrap: "wrap" }}>
              {["confirm", "reclassify", "reject", "false_positive", "escalate"].map((d) => (
                <button key={d} role="radio" aria-checked={decision === d} className={decision === d ? "on" : ""} onClick={() => setDecision(d)}>{titleCase(d)}</button>
              ))}
            </div>
            <div className="help">
              {decision === "confirm" && `Confirms the system classification (${CLASS_META[ev.classification ?? "unknown"].label}). Stored as an adjudicated training label.`}
              {decision === "reclassify" && "Records your classification instead of the system's. Stored as an adjudicated training label."}
              {decision === "reject" && "The classification is wrong or unsupported."}
              {decision === "false_positive" && "Not a genuine thermal source of interest. The reason feeds false-positive intelligence."}
              {decision === "escalate" && "Flags the event for supervisor attention and keeps the investigation open."}
            </div>
          </div>
          {decision === "reclassify" && (
            <div className="field"><label htmlFor="cls">Classification</label>
              <select id="cls" className="select" value={cls} onChange={(e) => setCls(e.target.value)}>
                {CLASS_ORDER.map((c) => <option key={c} value={c}>{CLASS_META[c].label}</option>)}
              </select></div>
          )}
          {decision === "false_positive" && (
            <div className="field"><label htmlFor="fp">Reason</label>
              <select id="fp" className="select" value={reason} onChange={(e) => setReason(e.target.value)}>
                {Object.entries(FP_REASONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select></div>
          )}
          <div className="field"><label htmlFor="rnotes">Rationale (optional)</label>
            <textarea id="rnotes" className="textarea" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="What evidence did you rely on?" /></div>
          <div><button className="btn primary" onClick={submit} disabled={review.isPending}>{review.isPending && <span className="spinner" />} Record decision</button></div>
        </div>
      ) : (
        <div className="faint">Viewers can inspect events but not record decisions. Ask an administrator for the analyst role.</div>
      )}

      <div className="divider" />
      <h4>Notes & attachments</h4>
      {analyst && (
        <div className="stack" style={{ gap: 6 }}>
          <textarea className="textarea" aria-label="New note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add an investigation note" />
          <div className="row"><input className="input" style={{ flex: 1 }} aria-label="Evidence link" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Optional evidence link (https://…)" />
            <button className="btn" onClick={submitNote} disabled={!note.trim() || addNote.isPending}>Add</button></div>
        </div>
      )}
      {ev.notes.length ? ev.notes.map((n) => (
        <div key={n.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 6 }}>
          <div style={{ fontSize: 12.5, whiteSpace: "pre-wrap" }}>{n.body}</div>
          {n.url && <ExtLink href={n.url}>{n.url.replace(/^https?:\/\//, "").slice(0, 60)}</ExtLink>}
          <div className="faint" style={{ fontSize: 11 }}>{n.author ?? "analyst"} · {relTime(n.created_at)}</div>
        </div>
      )) : <div className="faint">No notes yet.</div>}

      <div className="divider" />
      <h4>Decision history</h4>
      {ev.reviews.length ? ev.reviews.map((r) => (
        <div key={r.id} style={{ fontSize: 12.5 }}>
          <b>{titleCase(r.decision)}</b>{r.source_class ? ` as ${CLASS_META[r.source_class as keyof typeof CLASS_META]?.label ?? r.source_class}` : ""}
          {r.false_positive_reason ? ` (${FP_REASONS[r.false_positive_reason] ?? r.false_positive_reason})` : ""}
          <span className="faint"> — {r.reviewer ?? "analyst"}, {relTime(r.created_at)}; system said {r.system_source_class ?? "—"} ({fmtNum(r.system_confidence_score, 2)})</span>
          {r.notes && <div className="muted">{r.notes}</div>}
        </div>
      )) : <div className="faint">No decisions recorded. All labels shown are automated.</div>}
    </div>
  );
}

export function EventActions({ ev, compact }: { ev: EventDetail; compact?: boolean }) {
  const { can } = useSession();
  const toast = useToast();
  const reports = useReports(ev.id);
  const wls = useWatchlists();
  const report = useAction(actions.report(), [["reports"]]);
  const enrich = useAction(actions.enrich(ev.public_id), [["jobs"], ["event"]]);
  const [wlOpen, setWlOpen] = useState(false);
  const latest = reports.data?.items[0];
  const analyst = can("analyst");

  const addToWatchlist = async (wlId: string) => {
    try {
      await actions.addWatchItem(wlId)({ kind: "location", label: `${ev.public_id} area`, latitude: ev.latitude, longitude: ev.longitude, radius_m: 5000 });
      toast("Added to watchlist (5 km around event)");
      setWlOpen(false);
      wls.refetch();
    } catch (e) { toast(errText(e), "error"); }
  };

  if (!analyst) return null;
  return (
    <div className="row wrap" style={{ gap: 6 }}>
      <button className={`btn ${compact ? "sm" : ""}`} onClick={async () => {
        try { await report.mutateAsync(ev.id); toast("Report queued — it will be ready in a few seconds"); } catch (e) { toast(errText(e), "error"); }
      }} disabled={report.isPending || latest?.status === "pending"}>
        <FileText size={14} /> {latest?.status === "pending" ? "Generating…" : "Generate report"}
      </button>
      {latest?.status === "ready" && (
        <button className={`btn ${compact ? "sm" : ""}`} onClick={() => downloadFile(`/reports/${latest.id}/download`, `${ev.public_id}.pdf`).catch((e) => toast(errText(e), "error"))}>
          Download PDF
        </button>
      )}
      <div style={{ position: "relative" }}>
        <button className={`btn ${compact ? "sm" : ""}`} onClick={() => setWlOpen((v) => !v)} aria-expanded={wlOpen}><Eye size={14} /> Watch area</button>
        {wlOpen && (
          <div className="float" style={{ position: "absolute", top: "110%", left: 0, zIndex: 30, minWidth: 220, padding: 6 }}>
            {wls.data?.length ? wls.data.map((w) => (
              <button key={w.id} className="btn ghost sm" style={{ width: "100%", justifyContent: "flex-start" }} onClick={() => addToWatchlist(w.id)}>{w.name}</button>
            )) : <div className="faint" style={{ padding: 6 }}>No watchlists yet. <Link to="/watchlists">Create one</Link>.</div>}
          </div>
        )}
      </div>
      <Link className={`btn ${compact ? "sm" : ""}`} to={`/alerts?new=1&lat=${ev.latitude.toFixed(5)}&lon=${ev.longitude.toFixed(5)}&name=${encodeURIComponent(`Activity near ${ev.public_id}`)}`}>
        <Bell size={14} /> Alert on area
      </Link>
      <button className={`btn ghost ${compact ? "sm" : ""}`} title="Refresh OSM, weather, imagery and geocoding for this event"
        onClick={async () => { try { await enrich.mutateAsync(undefined); toast("Enrichment queued"); } catch (e) { toast(errText(e), "error"); } }} disabled={enrich.isPending}>
        <RefreshCw size={14} /> Enrich
      </button>
    </div>
  );
}

export function SimilarEvents({ ev }: { ev: EventDetail }) {
  const q = useSimilar(ev.id);
  if (q.isLoading) return <span className="spinner" />;
  if (!q.data?.length) return <div className="faint">No comparable analysed events yet.</div>;
  return <div>{q.data.map((e) => <EventRowMini key={e.id} e={e} />)}</div>;
}

// ------------------------------------------------------------------ composed investigation
const TABS = ["Summary", "Evidence", "Facilities", "History", "Satellite", "Weather", "Model", "Review", "Provenance"] as const;
export type Tab = (typeof TABS)[number];

export function EventHeader({ ev }: { ev: EventDetail }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row wrap" style={{ gap: 8 }}>
        <h1 className="mono" style={{ fontSize: 15 }}>{ev.public_id}</h1>
        <StatePill state={ev.display_state} />
        <ModePill mode={ev.data_mode} />
        <span className={`pill ${ev.status === "active" ? "thermal" : ""}`}>{ev.status}</span>
        <PriorityPill score={ev.priority_score} tier={ev.priority_components?.tier} />
      </div>
      <div className="row wrap" style={{ gap: 10 }}>
        <ClassLabel cls={ev.classification} />
        <span className="muted num">p {fmtNum(ev.classification_probability, 2)} · confidence {fmtNum(ev.confidence_score, 2)} · data quality {ev.data_quality ?? "—"}</span>
      </div>
      <div className="confidence-note" title={CONFIDENCE_EXPLAINER}>{confidenceNote(ev.display_state)}</div>
      <div className="faint" style={{ fontSize: 12 }}>
        {[locationLabel(ev), ev.country].filter(Boolean).join(", ") || "No named place nearby"} · {coordsLabel(ev, 4)} · last detected {relTime(ev.last_detected)}
      </div>
    </div>
  );
}

export function Investigation({ ev, compact, initialTab = "Summary" }: { ev: EventDetail; compact?: boolean; initialTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  useEffect(() => setTab(initialTab), [ev.id, initialTab]);
  const byKind = (k: string) => ev.evidence.filter((e) => e.knowledge_type === k);
  return (
    <div>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "Summary" && (
          <>
            <div className="section"><h4>Investigation summary</h4><AnswerGrid ev={ev} /></div>
            <div className="section"><h4>How ThermalTrace thinks</h4><EvidenceChain ev={ev} /></div>
            <div className="section"><h4>Why is this prioritised?</h4><PriorityPanel p={ev.priority_components} /></div>
            <div className="section"><h4>Evidence confidence matrix</h4><div className="table-wrap"><EvidenceMatrix ev={ev} /></div></div>
            <div className="section"><h4>Confidence components</h4><ConfidenceBreakdown ev={ev} /></div>
            <div className="section"><h4>Thermal fingerprint</h4><Fingerprint ev={ev} /></div>
          </>
        )}
        {tab === "Evidence" && ["observed", "derived", "external", "model"].map((k) => (
          <div className="section" key={k}>
            <h4>{({ observed: "Observed (satellite)", derived: "Derived by ThermalTrace", external: "External context", model: "Model output" } as Record<string, string>)[k]}</h4>
            <EvidenceList items={byKind(k)} compact={compact} />
          </div>
        ))}
        {tab === "Facilities" && <div className="section" style={{ padding: 0 }}><div className="table-wrap"><FacilityList ev={ev} /></div>
          <div className="section"><h4>Land cover (ESA WorldCover)</h4><LandCoverPanel ev={ev} /></div>
          {ev.land.length > 0 && <div className="section"><h4>Land use within 1.5 km (OSM)</h4>
            <div className="chips">{[...new Map(ev.land.map((l) => [l.category, l])).values()].map((l) => <span key={l.category} className="chip">{l.category} · {Math.round(l.distance_m)} m</span>)}</div></div>}
        </div>}
        {tab === "History" && (
          <>
            <div className="section"><PersistencePanel ev={ev} /></div>
            <div className="section"><h4>Timeline</h4><Timeline ev={ev} /></div>
            <div className="section"><h4>Similar events (fingerprint)</h4><SimilarEvents ev={ev} /></div>
          </>
        )}
        {tab === "Satellite" && (
          <>
            <div className="section"><h4>Spectral change (NDVI / NBR)</h4><SpectralChangePanel ev={ev} /></div>
            <div className="section"><h4>Scenes</h4><SatellitePanel ev={ev} /></div>
          </>
        )}
        {tab === "Weather" && <div className="section"><WeatherPanel ev={ev} /></div>}
        {tab === "Model" && <div className="section"><ModelPanel ev={ev} /></div>}
        {tab === "Review" && <div className="section"><ReviewPanel ev={ev} /></div>}
        {tab === "Provenance" && <div className="section" style={{ padding: 0 }}><Provenance ev={ev} /></div>}
      </div>
    </div>
  );
}
