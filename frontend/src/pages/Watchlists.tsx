import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { EventRowMini } from "../components/evidence";
import { Async, Empty, errText, useToast } from "../components/ui";
import { api } from "../lib/api";
import { fmtDistance, relTime } from "../lib/format";
import { actions, useAction, useWatchlists } from "../lib/hooks";
import { useSession } from "../lib/session";
import type { EventSummary, Watchlist } from "../lib/types";

function AddItem({ wl }: { wl: Watchlist }) {
  const toast = useToast();
  const [kind, setKind] = useState<"location" | "district" | "polygon">("location");
  const [label, setLabel] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [radius, setRadius] = useState("5");
  const [district, setDistrict] = useState("");
  const [poly, setPoly] = useState("");
  const add = useAction(actions.addWatchItem(wl.id), [["watchlists"], ["watch-events", wl.id]]);
  const submit = async () => {
    let body: Record<string, unknown>;
    if (kind === "location") body = { kind, label, latitude: +lat, longitude: +lon, radius_m: +radius * 1000 };
    else if (kind === "district") body = { kind, label: label || district, admin_district: district };
    else {
      try { body = { kind, label, polygon: JSON.parse(poly) }; } catch { toast("Polygon must be JSON: [[lon,lat], …] closed ring", "error"); return; }
    }
    try { await add.mutateAsync(body); toast("Added"); setLabel(""); setLat(""); setLon(""); setDistrict(""); setPoly(""); } catch (e) { toast(errText(e), "error"); }
  };
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="seg">{(["location", "district", "polygon"] as const).map((k) => <button key={k} className={kind === k ? "on" : ""} onClick={() => setKind(k)}>{k === "location" ? "Point + radius" : k === "district" ? "District" : "Custom polygon"}</button>)}</div>
      <div className="row wrap" style={{ alignItems: "flex-end" }}>
        <div className="field"><label htmlFor="wl-label">Label</label><input id="wl-label" className="input" value={label} onChange={(e) => setLabel(e.target.value)} /></div>
        {kind === "location" && <>
          <div className="field"><label htmlFor="wl-lat">Latitude</label><input id="wl-lat" className="input" type="number" step="any" style={{ width: 110 }} value={lat} onChange={(e) => setLat(e.target.value)} /></div>
          <div className="field"><label htmlFor="wl-lon">Longitude</label><input id="wl-lon" className="input" type="number" step="any" style={{ width: 110 }} value={lon} onChange={(e) => setLon(e.target.value)} /></div>
          <div className="field"><label htmlFor="wl-r">Radius km</label><input id="wl-r" className="input" type="number" min={0.1} style={{ width: 80 }} value={radius} onChange={(e) => setRadius(e.target.value)} /></div>
        </>}
        {kind === "district" && <div className="field"><label htmlFor="wl-d">District name</label><input id="wl-d" className="input" value={district} onChange={(e) => setDistrict(e.target.value)} placeholder="e.g. Dhanbad" /></div>}
        <button className="btn" onClick={submit} disabled={add.isPending || !(label || district) || (kind === "location" && (!lat || !lon)) || (kind === "polygon" && !poly)}>Add</button>
      </div>
      {kind === "polygon" && <textarea className="textarea mono" aria-label="Polygon coordinates" value={poly} onChange={(e) => setPoly(e.target.value)} placeholder="[[86.3,23.7],[86.5,23.7],[86.5,23.85],[86.3,23.85],[86.3,23.7]]" />}
      <div className="help faint" style={{ fontSize: 11.5 }}>Facilities and events can also be added from their pages ("Watch area").</div>
    </div>
  );
}

function WatchlistDetail({ wl }: { wl: Watchlist }) {
  const { can } = useSession();
  const events = useQuery({ queryKey: ["watch-events", wl.id], queryFn: () => api<{ items: (EventSummary & { is_new: boolean })[]; since: string }>(`/watchlists/${wl.id}/events`, { query: { limit: 50 } }) });
  const remove = useAction(actions.removeWatchItem(wl.id), [["watchlists"], ["watch-events", wl.id]]);
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1.3fr)" }}>
      <section className="panel"><div className="panel-head"><h2>Monitored targets</h2></div><div className="panel-body stack">
        {wl.items.length ? wl.items.map((i) => (
          <div key={i.id} className="row" style={{ justifyContent: "space-between" }}>
            <span><b>{i.label}</b> <span className="faint" style={{ fontSize: 12 }}>{i.kind}{i.radius_m ? ` · ${fmtDistance(i.radius_m)}` : ""}{i.facility_name ? ` · ${i.facility_name}` : ""}{i.admin_district ? ` · ${i.admin_district}` : ""}</span></span>
            {can("analyst") && <button className="btn ghost sm icon" aria-label={`Remove ${i.label}`} onClick={() => remove.mutate(i.id)}><Trash2 size={13} /></button>}
          </div>
        )) : <Empty title="Nothing monitored yet" />}
        {can("analyst") && <><div className="divider" /><AddItem wl={wl} /></>}
      </div></section>
      <section className="panel"><div className="panel-head"><h2>Matching events</h2><span className="right faint">new since {relTime(wl.summary.since)}: {wl.summary.new_since_viewed}</span></div>
        <div className="panel-body" style={{ paddingTop: 4 }}>
          <Async q={events} empty={(d) => (d.items.length ? null : <Empty title="No events in monitored areas" />)}>{(d) => <>{d.items.map((e) => (
            <div key={e.id} style={{ position: "relative" }}>{e.is_new && <span className="pill thermal" style={{ position: "absolute", right: 0, top: -2, height: 16, fontSize: 10 }}>new</span>}<EventRowMini e={e} /></div>
          ))}</>}</Async>
        </div></section>
    </div>
  );
}

export default function Watchlists() {
  const { can } = useSession();
  const toast = useToast();
  const wls = useWatchlists();
  const [sel, setSel] = useState<string | null>(null);
  const [name, setName] = useState("");
  const create = useAction(actions.createWatchlist(), [["watchlists"]]);
  const del = useAction(actions.deleteWatchlist(), [["watchlists"]]);
  const current = wls.data?.find((w) => w.id === sel) ?? wls.data?.[0];
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Watchlists</h1><div className="sub">Monitor facilities, locations, districts and custom areas. Counts show changes since you last opened each list.</div></div>
        {can("analyst") && <div className="actions">
          <input className="input" placeholder="New watchlist name" aria-label="New watchlist name" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn primary" disabled={!name.trim()} onClick={async () => { try { const w = await create.mutateAsync({ name }); setSel(w.id); setName(""); } catch (e) { toast(errText(e), "error"); } }}><Plus size={14} /> Create</button>
        </div>}
      </div>
      <Async q={wls} empty={(d) => (d.length ? null : <Empty title="No watchlists yet">Create one to monitor an industrial zone, district or facility.</Empty>)}>{(d) => (
        <>
          <div className="metrics" style={{ marginBottom: 12 }}>
            {d.map((w) => (
              <button key={w.id} className="metric" style={{ textAlign: "left", border: "none", background: current?.id === w.id ? "var(--surface-3)" : "transparent", cursor: "pointer" }} onClick={() => setSel(w.id)}>
                <div className="label">{w.name}</div>
                <div className="value">{w.summary.events}</div>
                <div className="hint">{w.summary.persistent} persistent · {w.summary.active} active · {w.summary.new_since_viewed} new</div>
              </button>
            ))}
          </div>
          {current && <>
            <div className="row" style={{ marginBottom: 8 }}><h2>{current.name}</h2><span style={{ flex: 1 }} />
              {can("analyst") && <button className="btn ghost sm danger" onClick={async () => { if (confirm(`Delete watchlist "${current.name}"?`)) { await del.mutateAsync(current.id); setSel(null); } }}>Delete list</button>}</div>
            <WatchlistDetail wl={current} />
          </>}
        </>
      )}</Async>
    </div>
  );
}
