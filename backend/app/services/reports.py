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
    "ANALYST_REVIEWED": "Analyst reviewed (neither confirmed nor rejected)",
}

REVIEW_LABELS = {
    "unreviewed": "Not reviewed", "under_review": "Under review", "escalated": "Escalated", "reviewed": "Reviewed",
    "analyst_confirmed": "Analyst confirmed", "analyst_rejected": "Analyst rejected", "false_positive": "False positive",
}


def _analyst_conclusion(ev: dict, last_review: dict | None) -> str:
    """The human decision, kept apart from the automated interpretation; never inferred when there is none."""
    status = REVIEW_LABELS.get(ev.get("review_status"), ev.get("review_status") or "Not reviewed")
    if not last_review:
        return f"{status}. No analyst decision recorded; the interpretation above is automated."
    label = CLASS_LABELS.get(last_review.get("source_class")) if last_review.get("source_class") else None
    return (f"{status}. Last decision: {last_review['decision'].replace('_', ' ')}"
            + (f" as {label}" if label and last_review["decision"] in ("confirm", "reclassify") else "")
            + f" by {last_review['reviewer'] or 'analyst'}, {_fmt_dt(last_review['created_at'])}."
            + (f" Note: {last_review['notes'][:300]}" if last_review.get("notes") else ""))


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


def build_pdf(ev: dict, author: str | None, audit: list[dict] | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Table, TableStyle

    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7, leading=9, textColor=colors.HexColor("#555555"))
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11, spaceBefore=8, spaceAfter=3)
    grid = TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 7.5), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f3f5")), ("VALIGN", (0, 0), (-1, -1), "TOP")])

    def P(t, st=body):
        return Paragraph(str(t).replace("&", "&amp;").replace("<", "&lt;"), st)

    inv = ev.get("evidence_stages") or {}
    stages = inv.get("stages") or []
    comp = inv.get("completeness") or {"available": 0, "total": 13}
    cls = CLASS_LABELS.get(ev["classification"], ev["classification"] or "–")
    last_review = ev["reviews"][0] if ev["reviews"] else None
    dets = ev["detections"]
    bright = [d["brightness"] for d in dets if d.get("brightness") is not None]
    top = ev["facilities"][0] if ev["facilities"] else None

    story = []
    story.append(Paragraph(f"ThermalTrace investigation report — {ev['public_id']}", ss["Title"]))
    story.append(P(f"Generated {_fmt_dt(datetime.now(UTC))}" + (f" by {author}" if author else "") +
                   f". Data mode: {ev['data_mode'].upper()}.", small))

    # 1. executive summary
    story.append(Paragraph("1. Executive summary", h2))
    where = ", ".join(x for x in (ev.get("place_name") or ev.get("admin_district"), ev.get("admin_state") or ev.get("place_admin1")) if x)
    summary = [
        ["Event", ev["public_id"]],
        ["Location", f"{ev['latitude']:.5f}, {ev['longitude']:.5f}" + (f"  ({where})" if where else "")],
        ["Observed", f"{_fmt_dt(ev['first_detected'])} → {_fmt_dt(ev['last_detected'])}  ({ev['days_active']} active day(s))"],
        ["Automated interpretation", f"{cls} — {STATE_LABELS.get(ev['confidence_state'], ev['confidence_state'])} "
                                     f"(confidence {ev['confidence_score'] or 0:.2f}; supporting evidence, not a probability). "
                                     "Produced by rules or a model; not a verified fact."],
        ["Class score", (f"{ev['classification_probability']:.2f} for {cls} (the classifier's score for this class among the "
                         "classes it knows; not the probability of a fire or of its cause)")
         if ev.get("classification_probability") is not None else "not available"],
        ["Analyst conclusion", _analyst_conclusion(ev, last_review)],
        ["Evidence availability", f"{comp['available']} of {comp['total']} evidence stages available (availability, not confidence)"],
        ["Triage priority", f"{ev['priority_score'] or 0:.0f} / 100 (orders the review queue; not a risk score)"],
    ]
    story.append(Table([[P(a), P(b)] for a, b in summary], colWidths=[36 * mm, 136 * mm], style=grid))

    # 2. thermal evidence
    story.append(Paragraph("2. Thermal evidence (observed / derived)", h2))
    thermal = [
        ["Detections", f"{ev['observation_count']} from {ev['sensor_count']} platform(s): {', '.join(ev['sensors'])}"],
        ["FRP", f"max {ev['frp_max'] or 0:.1f} MW, mean {ev['frp_mean'] or 0:.1f} MW"],
        ["Brightness", f"max {max(bright):.0f} K, mean {sum(bright) / len(bright):.0f} K" if bright else "not reported"],
        ["Persistence", f"{(ev['persistence_class'] or '–')} (score {ev['persistence_score'] or 0:.2f}); "
                        f"{ev['days_active']} active day(s) over {ev['duration_hours'] or 0:.0f} h"],
    ]
    story.append(Table([[P(a), P(b)] for a, b in thermal], colWidths=[36 * mm, 136 * mm], style=grid))
    story.append(P("Higher thermal intensity does not by itself determine the cause of an event.", small))

    # 3. spatial evidence
    story.append(Paragraph("3. Spatial evidence", h2))
    story.append(Image(io.BytesIO(_schematic_map(ev)), width=100 * mm, height=81 * mm))
    within2 = sum(1 for f in ev["facilities"] if f["distance_m"] <= 2000)
    story.append(P(f"Mapped facilities within the 10 km search radius: {len(ev['facilities'])} ({within2} within the 2 km rule radius)."
                   + (f" Attributed facility: {top['name'] or 'unnamed'} ({top['facility_type']}), {top['distance_m'] / 1000:.2f} km, "
                      f"attribution score {top['attribution_score']:.2f}. Proximity is supporting evidence, not proof of causation." if top else "")))
    if ev["facilities"]:
        rows = [["Facility", "Type", "Distance", "Sources", "Attribution"]] + [
            [P(f["name"] or "unnamed"), f["facility_type"], f"{f['distance_m'] / 1000:.2f} km",
             ", ".join(sorted({s["source"] for s in (f["sources"] or [])})), f"{f['attribution_score']:.2f}"]
            for f in ev["facilities"][:8]]
        story.append(Table(rows, colWidths=[60 * mm, 32 * mm, 20 * mm, 30 * mm, 20 * mm], style=grid))
    lc = ev.get("landcover")
    story.append(P("Land cover (ESA WorldCover 2021): " + (", ".join(
        f"{k.replace('_', ' ')} {v:.0%}" for k, v in sorted((lc.get("fractions") or {}).items(), key=lambda kv: -kv[1])[:3])
        if lc else "not retrieved") + ". Context only; it does not decide the classification."))

    # 4. environmental evidence
    story.append(Paragraph("4. Environmental evidence", h2))
    if ev["weather"]:
        w = ev["weather"][0]
        story.append(P(f"Weather ({w['dataset']}, {_fmt_dt(w['observed_at'])}): {w['condition'] or '–'}, {w['temperature_c']} °C, "
                       f"RH {w['humidity_pct']}%, wind {w['wind_speed_ms']} m/s from {w['wind_direction_deg']}°. Context only; the "
                       "dispersion direction is inferred from wind and is not plume tracking."))
    else:
        story.append(P("Weather: not available for this event (see limitations)."))
    story.append(P(f"Sentinel-2 scenes: {len(ev['satellite'])} stored."))
    if ev["satellite"]:
        rows = [["Acquired", "Platform", "Cloud", "Relation", "Item"]] + [
            [_fmt_dt(s["acquired_at"]), s["platform"] or "–", "–" if s["cloud_cover"] is None else f"{s['cloud_cover']:.0f}%",
             s["relation"], P(s["item_id"], small)] for s in ev["satellite"]]
        story.append(Table(rows, colWidths=[32 * mm, 22 * mm, 14 * mm, 16 * mm, 88 * mm], style=grid))
    ia = ev.get("imagery_analysis")
    if ia and ia["status"] == "ok":
        d = ia["deltas"] or {}
        story.append(P(f"NDVI / NBR change (1 km window, cloud-masked): NDVI {d.get('ndvi', 0):+.2f}, NBR {d.get('nbr', 0):+.2f} — "
                       f"{(ia['finding'] or '').replace('_', ' ')}. Spectral change consistent with burning is supporting evidence, "
                       "not proof; no change does not rule out a fire."))
    else:
        story.append(P("NDVI / NBR change: " + ((ia or {}).get("reason") or "not computed for this event") + "."))

    # 5. explainability
    story.append(Paragraph("5. Explainability", h2))
    shown = False
    for p in ev["predictions"]:
        ex = p["explanation"] or {}
        if ex.get("kind") == "shap" and ex.get("contributions"):
            story.append(P(f"SHAP ({p['model_version_id']}). SHAP shows how features contributed to the model output. "
                           "It does not establish causation.", small))
            rows = [["Feature", "Value", "Contribution"]] + [
                [c["feature"], "–" if c["value"] is None else f"{c['value']:.3g}", f"{c['contribution']:+.3f}"] for c in ex["contributions"][:8]]
            story.append(Table(rows, colWidths=[60 * mm, 30 * mm, 30 * mm], style=grid))
            shown = True
        elif ex.get("trace"):
            story.append(P(f"Rule trace ({p['model_version_id']}): " + " → ".join(str(t.get("rule", t)) if isinstance(t, dict) else str(t)
                                                                           for t in ex["trace"][:8]), small))
            shown = True
    if not shown:
        story.append(P("No model explanation recorded."))
    comps = (ev.get("confidence_components") or {}).get("components") or []
    if comps:
        rows = [["Confidence component", "Value", "Weight", "Explanation"]] + [
            [c["name"], f"{c['value']:.2f}", f"{c['weight']:.2f}", P(c["explanation"])] for c in comps]
        story.append(Table(rows, colWidths=[34 * mm, 14 * mm, 14 * mm, 110 * mm], style=grid, repeatRows=1))
    rows = [["Category", "Kind", "Direction", "Statement"]] + [
        [e["category"], e["knowledge_type"], e["direction"], P(e["statement"])] for e in ev["evidence"]]
    story.append(Table(rows, colWidths=[20 * mm, 16 * mm, 18 * mm, 118 * mm], style=grid, repeatRows=1))

    # 6. evidence stages: state, source and time of every stage; limitations of the missing ones
    story.append(Paragraph("6. Evidence stages, freshness and limitations", h2))
    fr = inv.get("freshness") or {}
    story.append(P(f"Heat last observed {_fmt_dt(fr.get('latest_observation_at'))}; evidence last refreshed "
                   f"{_fmt_dt(fr.get('latest_evidence_refresh_at'))}; record last updated {_fmt_dt(fr.get('record_updated_at'))}.", small))
    if stages:
        rows = [["Stage", "State", "Source", "Time", "Why / limitation"]] + [
            [st["title"], st["state_label"], P(st.get("source") or "", small), _fmt_dt(st.get("at")) if st.get("at") else "–",
             P((st.get("reason") if st["state"] != "available" else st.get("limitation")) or "", small)] for st in stages]
        story.append(Table(rows, colWidths=[34 * mm, 24 * mm, 38 * mm, 26 * mm, 50 * mm], style=grid, repeatRows=1))
    else:
        story.append(P("Evidence stages were not available for this event."))

    # 7. audit history
    story.append(Paragraph("7. Analyst decisions and audit history", h2))
    if ev["reviews"]:
        rows = [["When", "Reviewer", "Decision", "Status change", "Notes"]] + [
            [_fmt_dt(r["created_at"]), r["reviewer"] or "analyst", r["decision"].replace("_", " "),
             f"{REVIEW_LABELS.get(r.get('previous_status'), '–')} → {REVIEW_LABELS.get(r.get('new_status'), '–')}",
             P(r["notes"] or "", small)] for r in ev["reviews"][:15]]
        story.append(Table(rows, colWidths=[30 * mm, 28 * mm, 24 * mm, 36 * mm, 54 * mm], style=grid, repeatRows=1))
    else:
        story.append(P("No analyst decision recorded. Every interpretation above is automated."))
    if ev.get("notes"):
        story.append(Paragraph("Analyst notes", h2))
        rows = [["When", "Author", "Note"]] + [[_fmt_dt(n["created_at"]), n.get("author") or "analyst",
                                                P((n["body"] or "") + (f"  ({n['url']})" if n.get("url") else ""), small)]
                                               for n in ev["notes"][:30]]
        story.append(Table(rows, colWidths=[30 * mm, 30 * mm, 112 * mm], style=grid, repeatRows=1))
    if audit:
        rows = [["When", "Action", "By"]] + [[_fmt_dt(a["occurred_at"]), a["action"], a["user"] or "system"] for a in audit[:20]]
        story.append(Table(rows, colWidths=[34 * mm, 90 * mm, 48 * mm], style=grid, repeatRows=1))

    story.append(Paragraph("Timeline", h2))
    rows = [["Time", "Event", "Detail"]] + [[_fmt_dt(t["at"]), t["label"], P(t["detail"] or "", small)] for t in ev["timeline"][:40]]
    story.append(Table(rows, colWidths=[34 * mm, 50 * mm, 88 * mm], style=grid, repeatRows=1))

    # 8. methodology
    story.append(Paragraph("8. Methodology", h2))
    story.append(P(
        f"Detections: NASA FIRMS active-fire pixels (MODIS 1 km, VIIRS 375 m). Clustering: pixels within "
        f"{settings.cluster_radius_m:.0f} m and {settings.cluster_gap_days} day(s) of each other form one event. Facility "
        f"attribution: mapped facilities within {settings.attribution_radius_m / 1000:.0f} km, scored by distance decay "
        "(supporting evidence, not proof). Persistence: active days over the event span and the location's history. "
        "Land cover: ESA WorldCover 10 m (2021) in a 1.5 km window. Weather: Open-Meteo (ERA5 reanalysis or recent "
        "hourly model). Imagery: Sentinel-2 L2A scenes (Element84 Earth Search); NDVI / NBR change from cloud-masked "
        "1 km windows before and after the event. Classification: a documented rule cascade, or an administrator-activated "
        f"model ({(ev.get('classification_current') or {}).get('primary_model_id') or 'rule cascade'} for this event). "
        "Confidence: named components (model output, context, persistence, sensor agreement, imagery, data quality). "
        "Evidence availability counts the stages with evidence; it is not confidence. Triage priority orders the review "
        "queue; it is not a risk score."))

    # 9. disclaimer
    story.append(Paragraph("9. Disclaimer", h2))
    story.append(P("Automated classifications, confidence and attribution in this report are supporting evidence. They do not "
                   "establish causation and do not replace human review. Confidence reflects the available evidence supporting the "
                   "classification; it is not the probability of a fire. Proximity to a facility does not prove that the facility "
                   "caused the heat; spectral change does not prove burning; a model prediction does not prove the actual cause. "
                   "An event is confirmed only after imagery confirmation or analyst review."))
    story.append(Paragraph("Sources and attribution", h2))
    story.append(P("NASA FIRMS (MODIS C6.1, VIIRS 375 m: S-NPP, NOAA-20, NOAA-21), firms.modaps.eosdis.nasa.gov · "
                   "© OpenStreetMap contributors (ODbL) · Copernicus Sentinel-2 data via Element84 Earth Search · "
                   "ESA WorldCover 2021 (CC BY 4.0) · Weather: Open-Meteo (CC BY 4.0) · Facility registries as listed per facility.", small))
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
        from sqlalchemy import text

        audit = [dict(r) for r in db.execute(text(
            """SELECT a.occurred_at, a.action, u.full_name AS user FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id
               WHERE a.entity_type = 'event' AND a.entity_id = :id ORDER BY a.occurred_at DESC LIMIT 20"""),
            {"id": str(report.event_id)}).mappings()]
        pdf = build_pdf(get_bundle(db, report.event_id), author, audit)
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
