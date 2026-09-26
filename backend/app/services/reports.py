"""Event investigation report (PDF). Rendered by the worker; never implies autonomous verification."""
import hashlib
import io
import logging
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.gis.geo import compass, destination
from app.ml.base import CLASS_LABELS
from app.models.workflow import Report
from app.repositories.events import get_bundle

logger = logging.getLogger(__name__)
STATE_LABELS = {
    "CONFIRMED": "Confirmed (multi-source)", "HIGH_CONFIDENCE": "High confidence", "MODERATE_CONFIDENCE": "Moderate confidence",
    "LOW_CONFIDENCE": "Low confidence", "INSUFFICIENT_EVIDENCE": "Insufficient evidence — manual review required",
    "UNDER_REVIEW": "Under review", "ANALYST_CONFIRMED": "Analyst confirmed", "ANALYST_REJECTED": "Analyst rejected",
}


def _schematic_map(ev: dict) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.2, 4.2), dpi=150)
    lat0, lon0 = ev["latitude"], ev["longitude"]
    kx = 111.32 * math.cos(math.radians(lat0))

    def xy(lat, lon):
        return (lon - lon0) * kx, (lat - lat0) * 111.32

    dets = ev["detections"]
    if dets:
        pts = [xy(d["latitude"], d["longitude"]) for d in dets]
        sizes = [8 + min((d["frp"] or 0), 150) / 3 for d in dets]
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=sizes, c="#d9480f", alpha=0.55, lw=0, label="FIRMS detections")
    for f in ev["facilities"][:6]:
        x, y = xy(f["latitude"], f["longitude"])
        ax.scatter([x], [y], marker="s", s=36, c="#1c3d5a", zorder=3)
        ax.annotate((f["name"] or f["facility_type"])[:28], (x, y), fontsize=6, xytext=(4, 3), textcoords="offset points")
    w = ev["weather"][0] if ev["weather"] else None
    if w and w["wind_direction_deg"] is not None:
        b = (w["wind_direction_deg"] + 180) % 360
        tlat, tlon = destination(lat0, lon0, b, 2000)
        tx, ty = xy(tlat, tlon)
        ax.scatter([tx], [ty], s=0)  # extend the data limits so the arrow is inside the plot
        ax.annotate("", xy=(tx, ty), xytext=(0, 0), arrowprops=dict(arrowstyle="->", color="#1971c2", lw=1.4))
        ax.text(tx, ty, f" potential dispersion\n direction ({compass(b)})", fontsize=6, color="#1971c2")
    ax.scatter([0], [0], marker="+", s=80, c="black", zorder=4, label="event centroid")
    ax.set_xlabel("km east of centroid", fontsize=7)
    ax.set_ylabel("km north of centroid", fontsize=7)
    ax.tick_params(labelsize=6)
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, lw=0.3, alpha=0.5)
    ax.legend(fontsize=6, loc="lower right")
    ax.set_title("Schematic (no basemap): detections, facilities, wind", fontsize=7)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _fmt_dt(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    return v.strftime("%d %b %Y %H:%M UTC")


def build_pdf(ev: dict, author: str | None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7, leading=9, textColor=colors.HexColor("#555555"))
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11, spaceBefore=8, spaceAfter=3)
    grid = TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 7.5), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f3f5")), ("VALIGN", (0, 0), (-1, -1), "TOP")])

    def P(t, st=body):
        return Paragraph(str(t).replace("&", "&amp;").replace("<", "&lt;"), st)

    story = []
    story.append(Paragraph(f"ThermalTrace event report — {ev['public_id']}", ss["Title"]))
    story.append(P(f"Generated {_fmt_dt(datetime.now(UTC))}" + (f" by {author}" if author else "") +
                   f". Data mode: {ev['data_mode'].upper()}.", small))
    story.append(P("This report summarises automated analysis of satellite thermal detections and third-party context. "
                   "Classifications are automated assessments. Confidence reflects the available evidence supporting the "
                   "classification; it is not the probability of a fire, and supporting evidence is not proof. An event is "
                   "confirmed only after imagery confirmation or analyst review (see the analyst assessment below).", small))
    story.append(Spacer(1, 4))

    cls = CLASS_LABELS.get(ev["classification"], ev["classification"] or "–")
    summary = [
        ["Location", f"{ev['latitude']:.5f}, {ev['longitude']:.5f}  ({ev.get('admin_district') or '–'}, {ev.get('admin_state') or '–'})"],
        ["Observed", f"{_fmt_dt(ev['first_detected'])} → {_fmt_dt(ev['last_detected'])}  ({ev['days_active']} active day(s))"],
        ["Detections", f"{ev['observation_count']} from {ev['sensor_count']} platform(s): {', '.join(ev['sensors'])}"],
        ["FRP", f"max {ev['frp_max'] or 0:.1f} MW, mean {ev['frp_mean'] or 0:.1f} MW"],
        ["Classification", f"{cls} (model probability {ev['classification_probability'] or 0:.2f})"],
        ["Persistence", f"{(ev['persistence_class'] or '–').upper()} (score {ev['persistence_score'] or 0:.2f})"],
        ["System confidence", f"{STATE_LABELS.get(ev['confidence_state'], ev['confidence_state'])} — {ev['confidence_score'] or 0:.2f}"],
        ["Displayed status", STATE_LABELS.get(ev["display_state"], ev["display_state"])],
        ["Data quality", f"{(ev['data_quality'] or '–').title()}"],
    ]
    story.append(Table([[P(a), P(b)] for a, b in summary], colWidths=[32 * mm, 140 * mm], style=grid))

    story.append(Paragraph("Map (schematic)", h2))
    story.append(Image(io.BytesIO(_schematic_map(ev)), width=110 * mm, height=89 * mm))

    story.append(Paragraph("Evidence", h2))
    rows = [["Category", "Kind", "Direction", "Statement"]] + [
        [e["category"], e["knowledge_type"], e["direction"], P(e["statement"])] for e in ev["evidence"]]
    story.append(Table(rows, colWidths=[20 * mm, 16 * mm, 18 * mm, 118 * mm], style=grid, repeatRows=1))

    comps = (ev.get("confidence_components") or {}).get("components") or []
    if comps:
        story.append(Paragraph("Confidence components", h2))
        rows = [["Component", "Value", "Weight", "Explanation"]] + [
            [c["name"], f"{c['value']:.2f}", f"{c['weight']:.2f}", P(c["explanation"])] for c in comps]
        story.append(Table(rows, colWidths=[34 * mm, 14 * mm, 14 * mm, 110 * mm], style=grid, repeatRows=1))

    for p in ev["predictions"]:
        contribs = (p["explanation"] or {}).get("contributions") or []
        if (p["explanation"] or {}).get("kind") == "shap" and contribs:
            story.append(Paragraph(f"Model evidence (SHAP, {p['model_version_id']})", h2))
            story.append(P("SHAP values show which features moved this model's output. They are model evidence, not causal proof.", small))
            rows = [["Feature", "Value", "Contribution"]] + [
                [c["feature"], "–" if c["value"] is None else f"{c['value']:.3g}", f"{c['contribution']:+.3f}"] for c in contribs[:8]]
            story.append(Table(rows, colWidths=[60 * mm, 30 * mm, 30 * mm], style=grid))

    story.append(Paragraph("Nearby facilities", h2))
    if ev["facilities"]:
        rows = [["Facility", "Type", "Distance", "Sources", "Attribution"]] + [
            [P(f["name"] or "unnamed"), f["facility_type"], f"{f['distance_m'] / 1000:.2f} km",
             ", ".join(sorted({s["source"] for s in (f["sources"] or [])})), f"{f['attribution_score']:.2f}"]
            for f in ev["facilities"][:8]]
        story.append(Table(rows, colWidths=[60 * mm, 32 * mm, 20 * mm, 30 * mm, 20 * mm], style=grid))
    else:
        story.append(P("No mapped facility within 10 km in loaded sources (OSM coverage may be incomplete)."))

    story.append(Paragraph("Weather and satellite", h2))
    if ev["weather"]:
        w = ev["weather"][0]
        story.append(P(f"{w['dataset']} at {_fmt_dt(w['observed_at'])}: {w['condition'] or '–'}, {w['temperature_c']} °C, "
                       f"RH {w['humidity_pct']}%, wind {w['wind_speed_ms']} m/s from {w['wind_direction_deg']}°. "
                       "Dispersion direction is inferred from wind only — it is not plume tracking."))
    else:
        story.append(P("Weather context unavailable."))
    if ev["satellite"]:
        rows = [["Acquired", "Platform", "Level", "Cloud", "Relation", "Item"]] + [
            [_fmt_dt(s["acquired_at"]), s["platform"] or "–", s["processing_level"] or "–",
             "–" if s["cloud_cover"] is None else f"{s['cloud_cover']:.0f}%", s["relation"], P(s["item_id"], small)]
            for s in ev["satellite"]]
        story.append(Table(rows, colWidths=[32 * mm, 22 * mm, 12 * mm, 14 * mm, 16 * mm, 76 * mm], style=grid))
        story.append(P("Imagery is listed for analyst comparison; it was not analysed automatically.", small))
    else:
        story.append(P("No Sentinel-2 scene retrieved for this event."))

    story.append(Paragraph("Timeline", h2))
    rows = [["Time", "Event", "Detail"]] + [[_fmt_dt(t["at"]), t["label"], P(t["detail"] or "", small)] for t in ev["timeline"][:40]]
    story.append(Table(rows, colWidths=[34 * mm, 50 * mm, 88 * mm], style=grid, repeatRows=1))

    story.append(Paragraph("Analyst assessment", h2))
    if ev["reviews"]:
        for r in ev["reviews"][:10]:
            story.append(P(f"{_fmt_dt(r['created_at'])} — {r['reviewer'] or 'analyst'}: {r['decision'].upper()}"
                           + (f" as {r['source_class']}" if r["source_class"] else "")
                           + (f" (false positive: {r['false_positive_reason']})" if r["false_positive_reason"] else "")
                           + (f". Notes: {r['notes']}" if r["notes"] else "")))
    else:
        story.append(P("No analyst assessment recorded. All classifications above are automated."))

    story.append(Paragraph("Sources and attribution", h2))
    story.append(P("NASA FIRMS (MODIS C6.1, VIIRS 375 m: S-NPP, NOAA-20, NOAA-21), firms.modaps.eosdis.nasa.gov · "
                   "© OpenStreetMap contributors (ODbL) · Copernicus Sentinel-2 data via Element84 Earth Search · "
                   "Weather: Open-Meteo (CC BY 4.0) · Facility registries as listed per facility.", small))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                      title=f"ThermalTrace {ev['public_id']}", author="ThermalTrace").build(story)
    return buf.getvalue()


def render(db: Session, report_id: str) -> dict:
    report = db.get(Report, uuid.UUID(report_id))
    if report is None:
        raise ValueError("report not found")
    try:
        from app.models.auth import User

        author = db.get(User, report.created_by).full_name if report.created_by else None
        pdf = build_pdf(get_bundle(db, report.event_id), author)
        out_dir = Path(settings.report_storage_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{report.id}.pdf"
        path.write_bytes(pdf)
        report.file_path, report.size_bytes = str(path), len(pdf)
        report.sha256 = hashlib.sha256(pdf).hexdigest()
        report.status, report.completed_at = "ready", datetime.now(UTC)
    except Exception as exc:
        db.rollback()
        report = db.get(Report, uuid.UUID(report_id))
        report.status, report.error = "failed", f"{type(exc).__name__}: {exc}"[:1000]
        db.commit()
        raise
    db.commit()
    return {"report_id": report_id, "size": report.size_bytes}
