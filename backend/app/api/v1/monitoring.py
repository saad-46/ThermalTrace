"""Alert rules, alerts, watchlists, saved locations, reports."""
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import AnalystUser, CurrentUser, Page, pagination
from app.core.errors import AppError, Conflict, NotFound
from app.db.session import get_db
from app.models.auth import User
from app.models.workflow import Alert, AlertRule, Report, ReportExport, SavedLocation, Watchlist, WatchlistItem
from app.repositories.events import resolve_event_id
from app.schemas.api import (
    AlertOut,
    AlertRuleIn,
    AlertRuleOut,
    ReportIn,
    ReportOut,
    SavedLocationIn,
    WatchlistIn,
    WatchlistItemIn,
    WatchlistOut,
)
from app.schemas.api import Page as PageOut
from app.services import audit
from app.workers.queue import enqueue

router = APIRouter()


# --- alert rules -----------------------------------------------------------------------------------
def _rule_out(db: Session, r: AlertRule) -> dict:
    pt = db.execute(text("SELECT ST_Y(center::geometry) lat, ST_X(center::geometry) lon FROM alert_rules WHERE id=:i"), {"i": r.id}).one()
    n = db.execute(select(func.count(Alert.id)).where(Alert.rule_id == r.id)).scalar_one()
    return {**{c.key: getattr(r, c.key) for c in AlertRule.__table__.columns if c.key != "center"},
            "latitude": pt.lat, "longitude": pt.lon, "alert_count": n}


def _owned_rule(db: Session, rule_id: uuid.UUID, user: User) -> AlertRule:
    r = db.get(AlertRule, rule_id)
    if r is None or (r.owner_id != user.id and user.role != "admin"):
        raise NotFound("Alert rule not found")
    return r


def _apply_rule(r: AlertRule, body: AlertRuleIn) -> None:
    if (body.latitude is None) != (body.longitude is None):
        raise AppError("Provide both latitude and longitude, or neither", code="invalid_center")
    if body.latitude is None and body.watchlist_id is None and not (
            body.source_classes or body.facility_types or body.min_priority is not None
            or body.min_repeat_events is not None or body.activity_increase):
        raise AppError("A rule needs a location, a watchlist, or class/facility criteria", code="rule_too_broad")
    data = body.model_dump(exclude={"latitude", "longitude"})
    for k, v in data.items():
        setattr(r, k, v)
    r.center = f"SRID=4326;POINT({body.longitude} {body.latitude})" if body.latitude is not None else None


@router.get("/alert-rules", response_model=list[AlertRuleOut], tags=["alerts"])
def list_rules(user: User = CurrentUser, db: Session = Depends(get_db)):
    rules = db.execute(select(AlertRule).where(AlertRule.owner_id == user.id).order_by(AlertRule.created_at.desc())).scalars()
    return [_rule_out(db, r) for r in rules]


@router.post("/alert-rules", response_model=AlertRuleOut, status_code=201, tags=["alerts"])
def create_rule(body: AlertRuleIn, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    if body.watchlist_id:
        wl = db.get(Watchlist, body.watchlist_id)
        if wl is None or wl.owner_id != user.id:
            raise NotFound("Watchlist not found")
    r = AlertRule(owner_id=user.id)
    _apply_rule(r, body)
    db.add(r)
    db.flush()
    audit.record(db, request, user.id, "alert_rule.create", "alert_rule", r.id)
    db.commit()
    # Evaluate against current events immediately so the rule is useful now, not only on the next ingest.
    from app.services.alerts import evaluate_rules

    recent = db.execute(text("SELECT id FROM thermal_events WHERE last_detected >= now() - interval '14 days'")).scalars().all()
    evaluate_rules(db, list(recent))
    return _rule_out(db, r)


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleOut, tags=["alerts"])
def update_rule(rule_id: uuid.UUID, body: AlertRuleIn, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    r = _owned_rule(db, rule_id, user)
    before = _rule_out(db, r)
    _apply_rule(r, body)
    db.flush()
    after = _rule_out(db, r)
    changed = {k: {"from": before[k], "to": after[k]} for k in after
               if k not in ("alert_count", "last_triggered_at", "created_at") and before.get(k) != after[k]}
    audit.record(db, request, user.id, "alert_rule.update", "alert_rule", r.id, jsonable_encoder({"changes": changed}))
    db.commit()
    return _rule_out(db, r)


@router.delete("/alert-rules/{rule_id}", status_code=204, tags=["alerts"])
def delete_rule(rule_id: uuid.UUID, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    r = _owned_rule(db, rule_id, user)
    db.delete(r)
    audit.record(db, request, user.id, "alert_rule.delete", "alert_rule", rule_id)
    db.commit()


# --- alerts ------------------------------------------------------------------------------------------
@router.get("/alerts", response_model=PageOut[AlertOut], tags=["alerts"])
def list_alerts(status: str | None = Query(None, pattern="^(new|acknowledged|resolved)$"), page: Page = Depends(pagination),
                user: User = CurrentUser, db: Session = Depends(get_db)):
    where = "a.user_id = :u" + (" AND a.status = :s" if status else "")
    params = {"u": user.id, "s": status}
    total = db.execute(text(f"SELECT count(*) FROM alerts a WHERE {where}"), params).scalar_one()
    rows = db.execute(text(f"""
        SELECT a.*, r.name AS rule_name, e.public_id AS event_public_id,
          COALESCE((SELECT json_agg(json_build_object('channel', d.channel, 'status', d.status, 'error', d.error,
                     'attempted_at', d.attempted_at)) FROM alert_deliveries d WHERE d.alert_id = a.id), '[]') AS deliveries
        FROM alerts a JOIN alert_rules r ON r.id = a.rule_id JOIN thermal_events e ON e.id = a.event_id
        WHERE {where} ORDER BY a.triggered_at DESC LIMIT :limit OFFSET :offset"""),
        {**params, "limit": page.limit, "offset": page.offset}).mappings().all()
    return {"items": [dict(r) for r in rows], "total": total, "limit": page.limit, "offset": page.offset}


@router.get("/alerts/unread-count", tags=["alerts"])
def unread(user: User = CurrentUser, db: Session = Depends(get_db)):
    return {"count": db.execute(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.status == "new")).scalar_one()}


@router.post("/alerts/{alert_id}/{action}", tags=["alerts"])
def alert_action(alert_id: uuid.UUID, action: str, user: User = CurrentUser, db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if a is None or a.user_id != user.id:
        raise NotFound("Alert not found")
    if action not in ("acknowledge", "resolve"):
        raise NotFound("Unknown action")
    a.status = "acknowledged" if action == "acknowledge" else "resolved"
    a.acknowledged_at = a.acknowledged_at or datetime.now(UTC)
    db.commit()
    return {"status": a.status}


# --- watchlists -------------------------------------------------------------------------------------
_WL_EVENTS = """
    SELECT DISTINCT e.id FROM thermal_events e
    JOIN watchlist_items w ON w.watchlist_id = :wl
    LEFT JOIN facilities wf ON wf.id = w.facility_id
    WHERE (w.geom IS NOT NULL AND ST_DWithin(e.geom, w.geom, COALESCE(w.radius_m, 0)))
       OR (wf.id IS NOT NULL AND ST_DWithin(e.geom, wf.geom, COALESCE(w.radius_m, 5000)))
       OR (w.admin_district IS NOT NULL AND lower(w.admin_district) = lower(e.admin_district))
       OR (w.event_id = e.id)
"""


def _owned_watchlist(db: Session, wl_id: uuid.UUID, user: User) -> Watchlist:
    wl = db.get(Watchlist, wl_id)
    if wl is None or wl.owner_id != user.id:
        raise NotFound("Watchlist not found")
    return wl


def _watchlist_out(db: Session, wl: Watchlist) -> dict:
    items = db.execute(text("""SELECT w.id, w.kind, w.label, w.facility_id, w.event_id, w.radius_m, w.admin_district,
        ST_AsGeoJSON(w.geom::geometry)::json AS geometry, f.name AS facility_name, f.facility_type
        FROM watchlist_items w LEFT JOIN facilities f ON f.id = w.facility_id WHERE w.watchlist_id = :id ORDER BY w.created_at"""),
        {"id": wl.id}).mappings().all()
    since = wl.last_viewed_at or wl.created_at
    summary = db.execute(text(f"""
        WITH m AS ({_WL_EVENTS})
        SELECT count(*) AS events,
               count(*) FILTER (WHERE e.first_detected >= :since) AS new_since_viewed,
               count(*) FILTER (WHERE e.persistence_class = 'persistent') AS persistent,
               count(*) FILTER (WHERE e.status = 'active') AS active,
               count(*) FILTER (WHERE e.updated_at >= :since AND e.first_detected < :since) AS changed_since_viewed,
               max(e.last_detected) AS latest
        FROM thermal_events e JOIN m ON m.id = e.id"""), {"wl": wl.id, "since": since}).mappings().one()
    return {"id": wl.id, "name": wl.name, "description": wl.description, "created_at": wl.created_at,
            "items": [dict(i) for i in items], "summary": {**dict(summary), "since": since}}


@router.get("/watchlists", response_model=list[WatchlistOut], tags=["watchlists"])
def list_watchlists(user: User = CurrentUser, db: Session = Depends(get_db)):
    wls = db.execute(select(Watchlist).where(Watchlist.owner_id == user.id).order_by(Watchlist.created_at.desc())).scalars()
    return [_watchlist_out(db, w) for w in wls]


@router.post("/watchlists", response_model=WatchlistOut, status_code=201, tags=["watchlists"])
def create_watchlist(body: WatchlistIn, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    wl = Watchlist(owner_id=user.id, name=body.name, description=body.description)
    db.add(wl)
    db.flush()
    audit.record(db, request, user.id, "watchlist.create", "watchlist", wl.id, {"name": body.name})
    db.commit()
    return _watchlist_out(db, wl)


@router.get("/watchlists/{wl_id}", response_model=WatchlistOut, tags=["watchlists"])
def get_watchlist(wl_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return _watchlist_out(db, _owned_watchlist(db, wl_id, user))


@router.delete("/watchlists/{wl_id}", status_code=204, tags=["watchlists"])
def delete_watchlist(wl_id: uuid.UUID, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    wl = _owned_watchlist(db, wl_id, user)
    audit.record(db, request, user.id, "watchlist.delete", "watchlist", wl.id, {"name": wl.name})
    db.delete(wl)
    db.commit()


@router.post("/watchlists/{wl_id}/items", response_model=WatchlistOut, status_code=201, tags=["watchlists"])
def add_item(wl_id: uuid.UUID, body: WatchlistItemIn, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    wl = _owned_watchlist(db, wl_id, user)
    item = WatchlistItem(watchlist_id=wl.id, kind=body.kind, label=body.label, radius_m=body.radius_m)
    if body.kind == "facility":
        if not body.facility_id:
            raise AppError("facility_id required", code="facility_required")
        item.facility_id, item.radius_m = body.facility_id, body.radius_m or 5000
    elif body.kind == "event":
        if not body.event_id:
            raise AppError("event_id required", code="event_required")
        item.event_id = body.event_id
    elif body.kind == "location":
        if body.latitude is None or body.longitude is None:
            raise AppError("latitude and longitude required", code="location_required")
        item.geom, item.radius_m = f"SRID=4326;POINT({body.longitude} {body.latitude})", body.radius_m or 5000
    elif body.kind == "polygon":
        ring = body.polygon or []
        if len(ring) < 4 or ring[0] != ring[-1]:
            raise AppError("polygon must be a closed ring of ≥4 [lon, lat] positions", code="invalid_polygon")
        item.geom = "SRID=4326;POLYGON((" + ", ".join(f"{p[0]} {p[1]}" for p in ring) + "))"
        item.radius_m = 0
    elif body.kind == "district":
        if not body.admin_district:
            raise AppError("admin_district required", code="district_required")
        item.admin_district = body.admin_district
    db.add(item)
    db.flush()
    audit.record(db, request, user.id, "watchlist.item_add", "watchlist", wl.id,
                 jsonable_encoder({"item": item.id, "kind": body.kind, "label": body.label}))
    db.commit()
    return _watchlist_out(db, wl)


@router.delete("/watchlists/{wl_id}/items/{item_id}", status_code=204, tags=["watchlists"])
def remove_item(wl_id: uuid.UUID, item_id: uuid.UUID, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    _owned_watchlist(db, wl_id, user)
    item = db.get(WatchlistItem, item_id)
    if item is None or item.watchlist_id != wl_id:
        raise NotFound("Item not found")
    audit.record(db, request, user.id, "watchlist.item_remove", "watchlist", wl_id, {"item": str(item_id), "kind": item.kind})
    db.delete(item)
    db.commit()


@router.get("/watchlists/{wl_id}/events", tags=["watchlists"], summary="Events matching a watchlist (marks it viewed)")
def watchlist_events(wl_id: uuid.UUID, page: Page = Depends(pagination), user: User = CurrentUser, db: Session = Depends(get_db)):
    from app.repositories.events import _LIST_COLS, _with_display

    wl = _owned_watchlist(db, wl_id, user)
    since = wl.last_viewed_at or wl.created_at
    rows = db.execute(text(f"""WITH m AS ({_WL_EVENTS})
        SELECT {_LIST_COLS}, (e.first_detected >= :since) AS is_new
        FROM thermal_events e JOIN m ON m.id = e.id LEFT JOIN facilities f ON f.id = e.nearest_facility_id
        ORDER BY e.last_detected DESC LIMIT :limit OFFSET :offset"""),
        {"wl": wl.id, "since": since, "limit": page.limit, "offset": page.offset}).mappings().all()
    wl.last_viewed_at = datetime.now(UTC)
    db.commit()
    return {"items": [_with_display(dict(r)) for r in rows], "since": since}


# --- saved locations ----------------------------------------------------------------------------------
@router.get("/saved-locations", tags=["watchlists"])
def list_locations(user: User = CurrentUser, db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, name, zoom, ST_Y(geom::geometry) latitude, ST_X(geom::geometry) longitude, created_at "
                           "FROM saved_locations WHERE user_id = :u ORDER BY created_at DESC"), {"u": user.id}).mappings().all()
    return [dict(r) for r in rows]


@router.post("/saved-locations", status_code=201, tags=["watchlists"])
def save_location(body: SavedLocationIn, user: User = CurrentUser, db: Session = Depends(get_db)):
    loc = SavedLocation(user_id=user.id, name=body.name, zoom=body.zoom, geom=f"SRID=4326;POINT({body.longitude} {body.latitude})")
    db.add(loc)
    db.commit()
    return {"id": loc.id}


@router.delete("/saved-locations/{loc_id}", status_code=204, tags=["watchlists"])
def delete_location(loc_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    loc = db.get(SavedLocation, loc_id)
    if loc is None or loc.user_id != user.id:
        raise NotFound("Saved location not found")
    db.delete(loc)
    db.commit()


# --- reports ----------------------------------------------------------------------------------------
@router.post("/reports", response_model=ReportOut, status_code=202, tags=["reports"], summary="Queue a PDF report for an event")
def create_report(body: ReportIn, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    eid = resolve_event_id(db, body.event_id)
    public_id = db.execute(text("SELECT public_id FROM thermal_events WHERE id=:i"), {"i": eid}).scalar()
    pending = db.execute(select(Report).where(Report.event_id == eid, Report.status == "pending")).scalar_one_or_none()
    if pending:
        raise Conflict("A report for this event is already being generated")
    rep = Report(event_id=eid, created_by=user.id, title=f"Event report {public_id}", status="pending")
    db.add(rep)
    db.flush()
    audit.record(db, request, user.id, "report.create", "report", rep.id, {"event": public_id})
    db.commit()
    enqueue(db, "render_report", {"report_id": str(rep.id)}, priority=5, created_by=user.id)
    return rep


@router.get("/reports", response_model=PageOut[ReportOut], tags=["reports"])
def list_reports(event_id: str | None = None, page: Page = Depends(pagination), user: User = CurrentUser, db: Session = Depends(get_db)):
    q = select(Report)
    if event_id:
        q = q.where(Report.event_id == resolve_event_id(db, event_id))
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    items = db.execute(q.order_by(Report.created_at.desc()).limit(page.limit).offset(page.offset)).scalars().all()
    return {"items": items, "total": total, "limit": page.limit, "offset": page.offset}


@router.get("/reports/{report_id}", response_model=ReportOut, tags=["reports"])
def get_report(report_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    rep = db.get(Report, report_id)
    if rep is None:
        raise NotFound("Report not found")
    return rep


@router.get("/reports/{report_id}/download", tags=["reports"], response_class=FileResponse)
def download_report(report_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    rep = db.get(Report, report_id)
    if rep is None or rep.status != "ready" or not rep.file_path:
        raise NotFound("Report is not available")
    path = Path(rep.file_path).resolve()
    if Path(settings.report_storage_dir).resolve() not in path.parents or not path.exists():
        raise NotFound("Report file missing")
    db.add(ReportExport(report_id=rep.id, user_id=user.id))
    db.commit()
    return FileResponse(path, media_type="application/pdf", filename=f"{rep.title.replace(' ', '_')}.pdf")
