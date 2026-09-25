import { useState } from "react";
import { fmtNum } from "../lib/format";
import { FEATURE_LABELS } from "../lib/taxonomy";
import type { Contribution } from "../lib/types";

/** Daily bars (count) with FRP-max markers — "how did this event evolve?" */
export function EvolutionChart({ days }: { days: { date: string; count: number; frp: number | null; sensors: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!days.length) return null;
  const W = 380, H = 110, P = 22;
  const maxC = Math.max(...days.map((d) => d.count), 1);
  const maxF = Math.max(...days.map((d) => d.frp ?? 0), 1);
  const bw = Math.max(4, (W - P * 2) / days.length - 3);
  const x = (i: number) => P + i * ((W - P * 2) / days.length);
  const h = hover !== null ? days[hover] : null;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Daily detections and peak FRP">
        <line x1={P} x2={W - P} y1={H - 18} y2={H - 18} stroke="var(--border-strong)" />
        {days.map((d, i) => {
          const bh = (d.count / maxC) * (H - 34);
          const fy = d.frp != null ? H - 18 - (d.frp / maxF) * (H - 34) : null;
          return (
            <g key={d.date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={x(i)} y={H - 18 - bh} width={bw} height={bh} fill={hover === i ? "var(--text-2)" : "var(--text-3)"} rx={1} />
              {fy != null && <rect x={x(i) - 1} y={fy - 1.5} width={bw + 2} height={3} fill="var(--thermal)" />}
              <rect x={x(i)} y={0} width={bw + 3} height={H} fill="transparent" />
            </g>
          );
        })}
        <text x={P} y={H - 4} fontSize={9.5} fill="var(--text-3)">{days[0].date.slice(5)}</text>
        <text x={W - P} y={H - 4} fontSize={9.5} fill="var(--text-3)" textAnchor="end">{days[days.length - 1].date.slice(5)}</text>
      </svg>
      <div className="row faint" style={{ fontSize: 11.5, minHeight: 18 }}>
        {h ? (
          <span className="num">{h.date}: {h.count} detection(s), peak FRP {fmtNum(h.frp)} MW, {h.sensors} platform(s)</span>
        ) : (
          <>
            <span className="row" style={{ gap: 4 }}><i style={{ width: 9, height: 9, background: "var(--text-3)" }} /> detections/day</span>
            <span className="row" style={{ gap: 4 }}><i style={{ width: 9, height: 3, background: "var(--thermal)" }} /> peak FRP</span>
          </>
        )}
      </div>
    </div>
  );
}

/** Stacked bars by category over time buckets. */
export function StackedBars({ buckets, series, colors, height = 160 }: {
  buckets: { key: string; values: Record<string, number> }[];
  series: string[];
  colors: Record<string, string>;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (!buckets.length) return null;
  const W = 720, H = height, P = 26;
  const totals = buckets.map((b) => series.reduce((s, k) => s + (b.values[k] ?? 0), 0));
  const max = Math.max(...totals, 1);
  const step = (W - P * 2) / buckets.length;
  const bw = Math.max(3, step - 3);
  const hb = hover !== null ? buckets[hover] : null;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Activity over time">
        {[0.5, 1].map((f) => (
          <g key={f}>
            <line x1={P} x2={W - P} y1={H - 18 - f * (H - 30)} y2={H - 18 - f * (H - 30)} stroke="var(--border)" strokeDasharray="2 3" />
            <text x={P - 4} y={H - 15 - f * (H - 30)} fontSize={9.5} textAnchor="end" fill="var(--text-3)">{Math.round(max * f)}</text>
          </g>
        ))}
        {buckets.map((b, i) => {
          let y = H - 18;
          return (
            <g key={b.key} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              {series.map((s) => {
                const v = b.values[s] ?? 0;
                const h = (v / max) * (H - 30);
                y -= h;
                return v ? <rect key={s} x={P + i * step} y={y} width={bw} height={h} fill={colors[s] ?? "var(--text-3)"} opacity={hover === null || hover === i ? 1 : 0.55} /> : null;
              })}
              <rect x={P + i * step} y={0} width={step} height={H} fill="transparent" />
            </g>
          );
        })}
        <line x1={P} x2={W - P} y1={H - 18} y2={H - 18} stroke="var(--border-strong)" />
        <text x={P} y={H - 4} fontSize={9.5} fill="var(--text-3)">{buckets[0].key}</text>
        <text x={W - P} y={H - 4} fontSize={9.5} fill="var(--text-3)" textAnchor="end">{buckets[buckets.length - 1].key}</text>
      </svg>
      <div className="faint num" style={{ fontSize: 11.5, minHeight: 18 }}>
        {hb ? `${hb.key}: ` + series.filter((s) => hb.values[s]).map((s) => `${s.replace(/_/g, " ")} ${hb.values[s]}`).join(" · ") : "Hover a bar for values"}
      </div>
    </div>
  );
}

/** Diverging SHAP bars. Labelled as model evidence, never causal. */
export function ContributionChart({ items, label }: { items: Contribution[]; label: string }) {
  if (!items.length) return <div className="faint">No attribution available.</div>;
  const max = Math.max(...items.map((c) => Math.abs(c.contribution)), 1e-6);
  return (
    <div className="stack" style={{ gap: 5 }} aria-label={label}>
      {items.map((c) => {
        const w = (Math.abs(c.contribution) / max) * 50;
        const pos = c.contribution >= 0;
        return (
          <div key={c.feature} style={{ display: "grid", gridTemplateColumns: "132px 1fr 52px", gap: 8, alignItems: "center", fontSize: 12 }}>
            <span title={c.feature} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {FEATURE_LABELS[c.feature] ?? c.feature}
              <span className="faint"> {c.value == null ? "n/a" : fmtNum(c.value, 2)}</span>
            </span>
            <div style={{ position: "relative", height: 10, background: "var(--surface-3)", borderRadius: 2 }}>
              <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: "var(--border-strong)" }} />
              <div style={{ position: "absolute", top: 0, bottom: 0, borderRadius: 2, background: pos ? "var(--info)" : "var(--warn)",
                left: pos ? "50%" : `${50 - w}%`, width: `${w}%` }} />
            </div>
            <span className="num mono" style={{ textAlign: "right", color: pos ? "var(--info)" : "var(--warn)" }}>
              {pos ? "+" : ""}{c.contribution.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function HBars({ rows, color = "var(--text-2)", format = (v: number) => fmtNum(v, 0) }: {
  rows: { label: string; value: number; sub?: string }[];
  color?: string;
  format?: (v: number) => string;
}) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className="stack" style={{ gap: 6 }}>
      {rows.map((r) => (
        <div key={r.label} style={{ display: "grid", gridTemplateColumns: "minmax(90px, 38%) 1fr 56px", gap: 8, alignItems: "center", fontSize: 12 }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.sub ?? r.label}>{r.label}</span>
          <div className="meter"><i style={{ width: `${(r.value / max) * 100}%`, background: color }} /></div>
          <span className="num" style={{ textAlign: "right" }}>{format(r.value)}</span>
        </div>
      ))}
    </div>
  );
}
