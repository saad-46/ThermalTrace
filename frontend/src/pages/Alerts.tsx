import { Plus, Trash2 } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Async, Empty, errText, useToast } from "../components/ui";
import { fmtDateTime, fmtDistance, relTime, titleCase } from "../lib/format";
import { actions, useAction, useAlerts, useRules, useWatchlists } from "../lib/hooks";
import { useSession } from "../lib/session";
import { CLASS_META, CLASS_ORDER, FACILITY_LABELS, PERSISTENCE_META } from "../lib/taxonomy";
import type { AlertExplanation, AlertRule } from "../lib/types";

type Draft = {
  name: string; latitude: string; longitude: string; radius_km: string; watchlist_id: string; source_classes: string[];
  persistence_classes: string[]; facility_types: string[]; facility_within_km: string; min_confidence: string; min_frp: string;
  min_duration_hours: string; channels: string[]; cooldown_minutes: string; min_priority: string; min_repeat_events: string;
  repeat_days: string; activity_increase: boolean; increase_factor: string; increase_window_days: string; repeat_within_km: string;
  min_active_days: string; min_evidence_stages: string;
};
const EMPTY_DRAFT: Draft = { name: "", latitude: "", longitude: "", radius_km: "5", watchlist_id: "", source_classes: [], persistence_classes: [],
  facility_types: [], facility_within_km: "", min_confidence: "", min_frp: "", min_duration_hours: "", channels: ["in_app"], cooldown_minutes: "60", min_priority: "", min_repeat_events: "", repeat_days: "30",
  activity_increase: false, increase_factor: "2", increase_window_days: "7", repeat_within_km: "", min_active_days: "", min_evidence_stages: "" };
const FAC_TYPES = ["refinery", "oil_gas", "flare_site", "power_plant_coal", "steel_plant", "cement_plant", "chemical_plant", "coal_mine", "mine", "factory", "industrial_area"];
const toggle = (l: string[], v: string) => (l.includes(v) ? l.filter((x) => x !== v) : [...l, v]);
const num = (s: string) => (s.trim() === "" ? null : Number(s));

function RuleForm({ initial, onDone, rule }: { initial: Draft; onDone: () => void; rule?: AlertRule }) {
  const [d, setD] = useState<Draft>(initial);
  const toast = useToast();
  const wls = useWatchlists();
  const save = useAction(rule ? actions.updateRule(rule.id) : actions.createRule(), [["rules"], ["alerts"], ["alerts-unread"]]);
  const submit = async () => {
    const body = {
      name: d.name, is_active: true, latitude: num(d.latitude), longitude: num(d.longitude),
      radius_m: d.latitude ? (num(d.radius_km) ?? 5) * 1000 : null, watchlist_id: d.watchlist_id || null,
      source_classes: d.source_classes, persistence_classes: d.persistence_classes, facility_types: d.facility_types,
      facility_within_m: d.facility_within_km ? Number(d.facility_within_km) * 1000 : null, min_confidence: num(d.min_confidence),
      min_frp: num(d.min_frp), min_duration_hours: num(d.min_duration_hours), channels: d.channels,
      cooldown_minutes: num(d.cooldown_minutes) ?? 0, min_priority: num(d.min_priority), min_repeat_events: num(d.min_repeat_events),
      repeat_days: num(d.repeat_days) ?? 30, activity_increase: d.activity_increase,
      increase_factor: num(d.increase_factor) ?? 2, increase_window_days: num(d.increase_window_days) ?? 7,
      repeat_within_m: d.repeat_within_km ? Number(d.repeat_within_km) * 1000 : null,
      min_active_days: num(d.min_active_days), min_evidence_stages: num(d.min_evidence_stages),
    };
    try { await save.mutateAsync(body); toast(rule ? "Rule updated" : "Rule created and evaluated against recent events"); onDone(); }
    catch (e) { toast(errText(e), "error"); }
  };
  const F = (k: keyof Draft, label: string, props: Record<string, unknown> = {}) => (
    <div className="field"><label htmlFor={`r-${k}`}>{label}</label>
      <input id={`r-${k}`} className="input" value={d[k] as string} onChange={(e) => setD({ ...d, [k]: e.target.value })} {...props} /></div>
  );
  return (
    <div className="panel-body stack" style={{ gap: 12 }}>
      {F("name", "Rule name", { placeholder: "e.g. Persistent sources near refineries in Gujarat" })}
      <div className="row wrap" style={{ alignItems: "flex-end" }}>
        {F("latitude", "Center latitude", { type: "number", step: "any", style: { width: 130 } })}
        {F("longitude", "Center longitude", { type: "number", step: "any", style: { width: 130 } })}
        {F("radius_km", "Radius (km)", { type: "number", min: 0.1, style: { width: 100 } })}
        <div className="field"><label htmlFor="r-wl">…or a watchlist</label>
          <select id="r-wl" className="select" value={d.watchlist_id} onChange={(e) => setD({ ...d, watchlist_id: e.target.value })}>
            <option value="">None</option>{wls.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select></div>
      </div>
      <div className="field"><label>Classifications (none = any)</label><div className="chips">
        {CLASS_ORDER.map((c) => <button type="button" key={c} className={`chip ${d.source_classes.includes(c) ? "on" : ""}`} aria-pressed={d.source_classes.includes(c)} onClick={() => setD({ ...d, source_classes: toggle(d.source_classes, c) })}><i className="swatch" style={{ background: CLASS_META[c].color }} />{CLASS_META[c].short}</button>)}
      </div></div>
      <div className="field"><label>Persistence (none = any)</label><div className="chips">
        {Object.entries(PERSISTENCE_META).map(([k, m]) => <button type="button" key={k} className={`chip ${d.persistence_classes.includes(k) ? "on" : ""}`} aria-pressed={d.persistence_classes.includes(k)} onClick={() => setD({ ...d, persistence_classes: toggle(d.persistence_classes, k) })}>{m.label}</button>)}
      </div></div>
      <div className="field"><label>Near facility types</label><div className="chips">
        {FAC_TYPES.map((t) => <button type="button" key={t} className={`chip ${d.facility_types.includes(t) ? "on" : ""}`} aria-pressed={d.facility_types.includes(t)} onClick={() => setD({ ...d, facility_types: toggle(d.facility_types, t) })}>{FACILITY_LABELS[t]}</button>)}
      </div></div>
      <div className="row wrap">
        {F("facility_within_km", "Facility within (km)", { type: "number", min: 0.1, style: { width: 130 } })}
        {F("min_confidence", "Min confidence (0–1)", { type: "number", min: 0, max: 1, step: 0.05, style: { width: 130 } })}
        {F("min_frp", "Min peak FRP (MW)", { type: "number", min: 0, style: { width: 130 } })}
        {F("min_duration_hours", "Min duration (h)", { type: "number", min: 0, style: { width: 130 } })}
        {F("min_priority", "Min triage priority (0–100)", { type: "number", min: 0, max: 100, style: { width: 150 } })}
        {F("min_active_days", "Min active days (persistence)", { type: "number", min: 1, max: 365, style: { width: 150 } })}
        {F("min_evidence_stages", "Min evidence stages (of 13)", { type: "number", min: 1, max: 13, style: { width: 150 } })}
      </div>
      <div className="help faint" style={{ marginTop: -6, fontSize: 11.5 }}>Evidence stages count how much evidence has been collected for the event; it is not a confidence score.</div>
      <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Repeated activity at the nearest facility</legend>
        <div className="row wrap" style={{ alignItems: "flex-end" }}>
          {F("min_repeat_events", "At least N events", { type: "number", min: 2, style: { width: 130 } })}
          {F("repeat_days", "within (days)", { type: "number", min: 1, max: 365, style: { width: 110 } })}
          {F("repeat_within_km", "within (km of the facility; blank = same nearest facility)", { type: "number", min: 0.1, max: 10, step: 0.1, style: { width: 130 } })}
        </div>
        <div className="row wrap" style={{ alignItems: "flex-end" }}>
          <label className="check"><input type="checkbox" checked={d.activity_increase} onChange={() => setD({ ...d, activity_increase: !d.activity_increase })} />Activity increase</label>
          {F("increase_factor", "current ≥ factor × previous", { type: "number", min: 1, max: 20, step: 0.5, style: { width: 110 }, disabled: !d.activity_increase })}
          {F("increase_window_days", "period (days)", { type: "number", min: 1, max: 90, style: { width: 100 }, disabled: !d.activity_increase })}
        </div>
        <div className="help faint" style={{ fontSize: 11.5 }}>Activity increase needs at least 3 events in the current period and at least the factor times the period before.</div>
        <div className="help faint" style={{ fontSize: 11.5 }}>Triage priority orders the review queue; it is not a risk score. Facility conditions never match events with no mapped facility nearby.</div>
      </fieldset>
      <div className="field"><label>Delivery</label><div className="row">
        {(["in_app", "email", "push"] as const).map((c) => <label key={c} className="check"><input type="checkbox" checked={d.channels.includes(c)} onChange={() => setD({ ...d, channels: toggle(d.channels, c) })} />{titleCase(c)}</label>)}
      </div><div className="help">Email and push are delivered only if configured on the server; skipped deliveries are recorded on each alert.</div></div>
      {F("cooldown_minutes", "Email/push cooldown (minutes)", { type: "number", min: 0, max: 10080, style: { width: 130 } })}
      <div className="help faint" style={{ marginTop: -6, fontSize: 11.5 }}>After an email or push is sent, further matches within this window still create in-app alerts but do not notify externally (recorded as skipped).</div>
      <div className="row"><button className="btn primary" onClick={submit} disabled={!d.name || save.isPending || !d.channels.length}>{rule ? "Save rule" : "Create rule"}</button>
        <button className="btn ghost" onClick={onDone}>Cancel</button></div>
    </div>
  );
}

/** Why was I alerted? The rule's conditions, their thresholds and what was observed when the alert was created. */
export function AlertWhy({ reason }: { reason: Record<string, unknown> }) {
  const x = reason.explanation as AlertExplanation | undefined;
  if (!x) {
    const pairs = Object.entries(reason).filter(([, v]) => v != null && typeof v !== "object");
    return (
      <div className="alert-why">
        <div className="faint" style={{ fontSize: 11.5 }}>This alert predates condition-level explanations. Values recorded when it was created:</div>
        <dl className="kv compact">{pairs.map(([k, v]) => <Fragment key={k}><dt>{titleCase(k)}</dt><dd>{String(v)}</dd></Fragment>)}</dl>
      </div>
    );
  }
  return (
    <div className="alert-why" data-testid="alert-why">
      <div><b>{x.summary}</b></div>
      <table className="table compact"><thead><tr><th scope="col">Condition</th><th scope="col">Threshold</th><th scope="col">Observed</th><th scope="col">Previous period</th><th scope="col">Result</th></tr></thead>
        <tbody>{x.conditions.map((c) => (
          <tr key={c.condition}><td>{c.label}</td><td className="num">{String(c.threshold ?? "—")}</td><td className="num">{String(c.observed ?? "—")}</td>
            <td className="num">{c.previous != null ? c.previous : "—"}</td><td>{c.result === "satisfied" ? "Condition satisfied" : c.result}</td></tr>
        ))}</tbody></table>
      <dl className="kv compact">
        <dt>Rule</dt><dd>{x.rule}{x.rule_snapshot && <span className="faint"> · conditions as they were when this alert was created</span>}</dd>
        <dt>Evaluated</dt><dd>{fmtDateTime(x.evaluated_at)}</dd>
        <dt>Event</dt><dd><Link className="mono" to={`/events/${x.event}`}>{x.event}</Link></dd>
        {x.facility && <><dt>Facility</dt><dd>{x.facility}{x.facility_distance_m != null ? ` · ${fmtDistance(x.facility_distance_m)}` : ""}</dd></>}
        <dt>Evidence</dt><dd>{[x.evidence.classification, x.evidence.confidence_state?.replace(/_/g, " ").toLowerCase(),
          x.evidence.priority != null ? `priority ${x.evidence.priority}` : null, x.evidence.evidence_stages != null ? `${x.evidence.evidence_stages}/13 evidence stages` : null].filter(Boolean).join(" · ")}</dd>
        <dt>Result</dt><dd><b>{x.result}</b> — cause not established</dd>
      </dl>
      <div className="faint" style={{ fontSize: 11.5 }}>{x.note}</div>
    </div>
  );
}

function draftFrom(r: AlertRule): Draft {
  return { name: r.name, latitude: r.latitude?.toString() ?? "", longitude: r.longitude?.toString() ?? "", radius_km: r.radius_m ? String(r.radius_m / 1000) : "5",
    watchlist_id: r.watchlist_id ?? "", source_classes: r.source_classes, persistence_classes: r.persistence_classes, facility_types: r.facility_types,
    facility_within_km: r.facility_within_m ? String(r.facility_within_m / 1000) : "", min_confidence: r.min_confidence?.toString() ?? "",
    min_frp: r.min_frp?.toString() ?? "", min_duration_hours: r.min_duration_hours?.toString() ?? "", channels: r.channels,
    cooldown_minutes: String(r.cooldown_minutes ?? 0), min_priority: r.min_priority?.toString() ?? "",
    min_repeat_events: r.min_repeat_events?.toString() ?? "", repeat_days: String(r.repeat_days ?? 30), activity_increase: !!r.activity_increase,
    increase_factor: String(r.increase_factor ?? 2), increase_window_days: String(r.increase_window_days ?? 7),
    repeat_within_km: r.repeat_within_m ? String(r.repeat_within_m / 1000) : "", min_active_days: r.min_active_days?.toString() ?? "",
    min_evidence_stages: r.min_evidence_stages?.toString() ?? "" };
}

export default function Alerts() {
  const [params, setParams] = useSearchParams();
  const { can } = useSession();
  const toast = useToast();
  const [status, setStatus] = useState<string | undefined>(undefined);
  const alerts = useAlerts(status);
  const rules = useRules();
  const [editing, setEditing] = useState<{ draft: Draft; rule?: AlertRule } | null>(null);
  const act = useAction(actions.alertAction(), [["alerts"], ["alerts-unread"]]);
  const remove = useAction(actions.deleteRule(), [["rules"]]);
  const [why, setWhy] = useState<string | null>(null);

  useEffect(() => {
    if (params.get("new")) {
      setEditing({ draft: { ...EMPTY_DRAFT, name: params.get("name") ?? "", latitude: params.get("lat") ?? "", longitude: params.get("lon") ?? "" } });
      setParams({}, { replace: true });
    }
  }, [params, setParams]);

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Alerts</h1><div className="sub">Rule-based notifications on classified events. An alert reflects an automated classification, not a verified incident.</div></div>
        {can("analyst") && <div className="actions"><button className="btn primary" onClick={() => setEditing({ draft: EMPTY_DRAFT })}><Plus size={14} /> New rule</button></div>}
      </div>
      {editing && <section className="panel" style={{ marginBottom: 12 }}><div className="panel-head"><h2>{editing.rule ? "Edit rule" : "New alert rule"}</h2></div>
        <RuleForm initial={editing.draft} rule={editing.rule} onDone={() => setEditing(null)} /></section>}
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.5fr) minmax(0, 1fr)" }}>
        <section className="panel">
          <div className="panel-head"><h2>Inbox</h2>
            <div className="right seg">{[[undefined, "All"], ["new", "New"], ["acknowledged", "Acknowledged"], ["resolved", "Resolved"]].map(([k, l]) => (
              <button key={l} className={status === k ? "on" : ""} onClick={() => setStatus(k)}>{l}</button>))}</div></div>
          <Async q={alerts} empty={(d) => (d.items.length ? null : <Empty title="No alerts">Alerts appear here when a rule matches a newly processed event.</Empty>)}>{(d) => (
            <div className="table-wrap"><table className="table"><thead><tr><th scope="col">Alert</th><th scope="col">Severity</th><th scope="col">Delivery</th><th scope="col">When</th><th scope="col" /></tr></thead>
              <tbody>{d.items.map((a) => (
                <Fragment key={a.id}><tr style={{ opacity: a.status === "resolved" ? 0.6 : 1 }}>
                  <td><Link to={`/events/${a.event_public_id}`} style={{ fontWeight: a.status === "new" ? 600 : 400 }}>{a.title}</Link>
                    <div className="faint" style={{ fontSize: 11.5 }}>{a.rule_name}{a.reason.facility_distance_m != null ? ` · facility ${fmtDistance(a.reason.facility_distance_m as number)}` : ""}</div>
                    <button className="btn ghost sm" aria-expanded={why === a.id} onClick={() => setWhy(why === a.id ? null : a.id)}>{why === a.id ? "Hide explanation" : "Why was I alerted?"}</button></td>
                  <td><span className={`pill ${a.severity === "critical" ? "rejected" : a.severity === "warning" ? "low" : ""}`}>{a.severity}</span></td>
                  <td style={{ fontSize: 11.5 }}>{a.deliveries.map((x) => <div key={x.channel} title={x.error ?? ""}>{x.channel}: <span className={x.status === "sent" ? "" : "faint"}>{x.status}</span>{x.error ? <span className="faint"> ({x.error})</span> : null}</div>)}</td>
                  <td className="num">{relTime(a.triggered_at)}</td>
                  <td className="right">{a.status === "new" && <button className="btn sm" onClick={() => act.mutate({ id: a.id, action: "acknowledge" })}>Acknowledge</button>}
                    {a.status !== "resolved" && <button className="btn ghost sm" onClick={() => act.mutate({ id: a.id, action: "resolve" })}>Resolve</button>}</td>
                </tr>
                {why === a.id && <tr><td colSpan={5}><AlertWhy reason={a.reason} /></td></tr>}</Fragment>
              ))}</tbody></table></div>
          )}</Async>
        </section>
        <section className="panel" data-tour-id="alerts-rules">
          <div className="panel-head"><h2>My rules</h2></div>
          <Async q={rules} empty={(d) => (d.length ? null : <Empty title="No rules yet">Example: "persistent events within 5 km of a refinery".</Empty>)}>{(d) => (
            <div>{d.map((r) => (
              <div key={r.id} className="section">
                <div className="row"><b>{r.name}</b><span style={{ flex: 1 }} />
                  <button className="btn ghost sm" onClick={() => setEditing({ draft: draftFrom(r), rule: r })}>Edit</button>
                  <button className="btn ghost sm icon" aria-label={`Delete rule ${r.name}`} onClick={async () => { if (confirm(`Delete rule "${r.name}"?`)) { try { await remove.mutateAsync(r.id); toast("Rule deleted"); } catch (e) { toast(errText(e), "error"); } } }}><Trash2 size={13} /></button></div>
                <div className="faint" style={{ fontSize: 12 }}>
                  {[r.latitude != null ? `${fmtDistance(r.radius_m)} around ${r.latitude.toFixed(3)}, ${r.longitude?.toFixed(3)}` : null, r.watchlist_id ? "watchlist" : null,
                    r.source_classes.length ? r.source_classes.map((c) => CLASS_META[c].short).join("/") : null,
                    r.persistence_classes.length ? r.persistence_classes.join("/") : null,
                    r.facility_types.length ? `within ${fmtDistance(r.facility_within_m)} of ${r.facility_types.map((t) => FACILITY_LABELS[t]).join("/")}` : null,
                    r.min_confidence != null ? `confidence ≥ ${r.min_confidence}` : null, r.min_frp != null ? `FRP ≥ ${r.min_frp} MW` : null,
                    r.min_priority != null ? `priority ≥ ${r.min_priority}` : null, r.min_active_days != null ? `≥ ${r.min_active_days} active days` : null,
                    r.min_evidence_stages != null ? `≥ ${r.min_evidence_stages}/13 evidence stages` : null,
                    r.min_repeat_events != null ? `≥ ${r.min_repeat_events} events in ${r.repeat_days} d${r.repeat_within_m ? ` within ${fmtDistance(r.repeat_within_m)}` : ""}` : null,
                    r.activity_increase ? `activity ≥ ${r.increase_factor}× previous ${r.increase_window_days} d` : null].filter(Boolean).join(" · ")}
                </div>
                <div className="faint" style={{ fontSize: 11.5 }}>{r.alert_count} alert(s) · {r.channels.join(", ")}{r.cooldown_minutes ? ` · ${r.cooldown_minutes} min cooldown` : ""} · last triggered {relTime(r.last_triggered_at)}</div>
              </div>
            ))}</div>
          )}</Async>
        </section>
      </div>
    </div>
  );
}
