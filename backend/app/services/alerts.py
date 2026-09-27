"""Rule-based alerting. Rules are evaluated in SQL against changed events; each (rule, event)
pair alerts at most once. Every delivery attempt is recorded, including skipped channels."""
import json
import logging
import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app.core.config import settings
from app.ml.base import CLASS_LABELS
from app.models.auth import PushSubscription, User
from app.models.workflow import Alert, AlertDelivery, AlertRule
from app.services.evidence_rules import completeness_sql

logger = logging.getLogger(__name__)

# Facility activity is counted for the event's nearest facility: events sharing it as their nearest facility, or,
# when the rule sets repeat_within_m, every event linked to it within that distance.
_FAC_EVENTS = """(SELECT count(DISTINCT o.id) FROM thermal_events o
                  WHERE e.nearest_facility_id IS NOT NULL AND {window} AND (
                    (r.repeat_within_m IS NULL AND o.nearest_facility_id = e.nearest_facility_id)
                    OR (r.repeat_within_m IS NOT NULL AND EXISTS (SELECT 1 FROM event_facility_links l2 WHERE l2.event_id = o.id
                        AND l2.facility_id = e.nearest_facility_id AND l2.distance_m <= r.repeat_within_m))))"""

_MATCH_SQL = text(
    f"""
    SELECT e.id, e.public_id, e.classification, e.persistence_class, e.confidence_score, e.confidence_state, e.frp_max,
           e.duration_hours, e.days_active, e.admin_district, e.admin_state, e.latitude, e.longitude, e.priority_score,
           e.nearest_facility_id, e.nearest_facility_distance_m, e.last_detected,
           (SELECT name FROM facilities WHERE id = e.nearest_facility_id) AS facility_name,
           {_FAC_EVENTS.format(window="o.last_detected >= now() - make_interval(days => r.repeat_days)")} AS facility_events,
           {_FAC_EVENTS.format(window="o.first_detected >= now() - make_interval(days => r.increase_window_days)")} AS fac_recent,
           {_FAC_EVENTS.format(window="o.first_detected >= now() - make_interval(days => 2 * r.increase_window_days) "
                                      "AND o.first_detected < now() - make_interval(days => r.increase_window_days)")} AS fac_prior,
           {completeness_sql('e')} AS evidence_stages,
           (SELECT min(l.distance_m) FROM event_facility_links l JOIN facilities f ON f.id = l.facility_id
             WHERE l.event_id = e.id AND (cardinality(r.facility_types) = 0 OR f.facility_type = ANY(r.facility_types))) AS fac_dist
    FROM thermal_events e, alert_rules r
    WHERE r.id = :rule_id AND e.id = ANY(:ids) AND e.classification IS NOT NULL
      AND e.last_detected >= now() - make_interval(hours => :max_age_h)
      AND e.data_mode <> 'demo'
      AND (r.center IS NULL OR ST_DWithin(e.geom, r.center, COALESCE(r.radius_m, 5000)))
      AND (r.watchlist_id IS NULL OR EXISTS (
            SELECT 1 FROM watchlist_items w LEFT JOIN facilities wf ON wf.id = w.facility_id
            WHERE w.watchlist_id = r.watchlist_id AND (
              (w.geom IS NOT NULL AND ST_DWithin(e.geom, w.geom, COALESCE(w.radius_m, 0)))
              OR (wf.id IS NOT NULL AND ST_DWithin(e.geom, wf.geom, COALESCE(w.radius_m, 5000)))
              OR (w.admin_district IS NOT NULL AND lower(w.admin_district) = lower(e.admin_district))
              OR (w.event_id = e.id))))
      AND (cardinality(r.source_classes) = 0 OR e.classification = ANY(r.source_classes))
      AND (cardinality(r.persistence_classes) = 0 OR e.persistence_class = ANY(r.persistence_classes))
      AND (r.min_confidence IS NULL OR e.confidence_score >= r.min_confidence)
      AND (r.min_frp IS NULL OR e.frp_max >= r.min_frp)
      AND (r.min_duration_hours IS NULL OR e.duration_hours >= r.min_duration_hours)
      AND (r.min_priority IS NULL OR e.priority_score >= r.min_priority)
      AND (r.min_active_days IS NULL OR e.days_active >= r.min_active_days)
      AND NOT EXISTS (SELECT 1 FROM alerts a WHERE a.rule_id = r.id AND a.event_id = e.id)
    """
)


def _severity(row) -> str:
    if row["classification"] == "industrial_fire" or (row["frp_max"] or 0) >= 100:
        return "critical"
    if row["persistence_class"] == "persistent" or (row["confidence_score"] or 0) >= 0.72:
        return "warning"
    return "info"


def evaluate_rules(db: Session, event_ids: list, rule_ids: list | None = None) -> dict:
    """Match events against active rules (all of them, or only `rule_ids`) and create alerts."""
    ids = [uuid.UUID(str(i)) for i in event_ids]
    if not ids:
        return {"alerts": 0}
    created = 0
    rules = select(AlertRule).where(AlertRule.is_active.is_(True))
    if rule_ids is not None:
        rules = rules.where(AlertRule.id.in_(rule_ids))
    for rule in db.execute(rules).scalars().all():
        matches = db.execute(_MATCH_SQL, {"rule_id": rule.id, "ids": ids, "max_age_h": settings.alert_max_event_age_hours}).mappings().all()
        new_alerts: list[Alert] = []
        for row in matches:
            if rule.facility_types and rule.facility_within_m is not None and (
                    row["fac_dist"] is None or row["fac_dist"] > rule.facility_within_m):
                continue
            if not repeat_and_increase_ok(rule, row["facility_events"], row["fac_recent"], row["fac_prior"]):
                continue
            if rule.min_evidence_stages is not None and (row["evidence_stages"] or 0) < rule.min_evidence_stages:
                continue
            label = CLASS_LABELS.get(row["classification"], row["classification"])
            reason = {
                "priority": row["priority_score"],
                "facility_events_in_window": row["facility_events"] if rule.min_repeat_events else None,
                "facility_events_last_7d": row["fac_recent"] if rule.activity_increase else None,
                "facility_events_prior_7d": row["fac_prior"] if rule.activity_increase else None,
                "rule": rule.name, "classification": row["classification"], "persistence": row["persistence_class"],
                "confidence": row["confidence_score"], "frp_max": row["frp_max"],
                "facility_distance_m": round(row["fac_dist"]) if row["fac_dist"] is not None else None,
                "explanation": explain(rule, row),
            }
            where = row["admin_district"] or f"{row['latitude']:.3f}, {row['longitude']:.3f}"
            alert = Alert(rule_id=rule.id, event_id=row["id"], user_id=rule.owner_id, severity=_severity(row),
                          title=f"{row['public_id']}: {label} ({row['persistence_class']}) — {where}", reason=reason)
            try:
                with db.begin_nested():  # another worker may have raised the same (rule, event) alert just now
                    db.add(alert)
                    db.flush()
            except IntegrityError:
                continue
            new_alerts.append(alert)
        if not new_alerts:
            continue
        rule.last_triggered_at = new_alerts[-1].triggered_at
        # Every alert is committed before anything leaves the system: a later failure can never produce an e-mail
        # without an alert, and a retry cannot send twice (existing alerts are never re-created). One commit per rule.
        db.commit()
        _lock_rule(db, rule)  # serialises the cooldown check between workers
        for alert in new_alerts:
            if deliver(db, alert, rule):  # something was sent (e-mail / push): record it at once, then carry on
                db.commit()
                _lock_rule(db, rule)
            created += 1
        db.commit()
    db.commit()
    return {"alerts": created}


def repeat_and_increase_ok(rule: AlertRule, facility_events: int, recent: int, prior: int) -> bool:
    """Facility-activity conditions. Both are about the event's nearest mapped facility, so an event with
    no facility nearby never satisfies them. `activity_increase` needs at least 3 events in the current
    window and at least `increase_factor` times the window before, so one or two new events never count as a surge."""
    if rule.min_repeat_events is not None and (facility_events or 0) < rule.min_repeat_events:
        return False
    factor = getattr(rule, "increase_factor", None) or 2.0
    if rule.activity_increase and not ((recent or 0) >= 3 and (recent or 0) >= factor * (prior or 0)):
        return False
    return True


def _cond(kind: str, label: str, threshold, observed, **extra) -> dict:
    return {"condition": kind, "label": label, "threshold": threshold, "observed": observed, "result": "satisfied", **extra}


# the rule fields that decide whether an event matches; copied into every alert so the explanation stays reproducible
# after the rule is edited or deleted
SNAPSHOT_FIELDS = ("name", "source_classes", "persistence_classes", "facility_types", "facility_within_m", "min_confidence",
                   "min_frp", "min_duration_hours", "min_priority", "min_repeat_events", "repeat_days", "repeat_within_m",
                   "activity_increase", "increase_factor", "increase_window_days", "min_active_days", "min_evidence_stages",
                   "radius_m", "watchlist_id", "cooldown_minutes", "channels")


def rule_snapshot(rule: AlertRule) -> dict:
    snap = {k: getattr(rule, k, None) for k in SNAPSHOT_FIELDS}
    snap["watchlist_id"] = str(snap["watchlist_id"]) if snap["watchlist_id"] else None
    snap["has_area"] = rule.center is not None
    for k in ("source_classes", "persistence_classes", "facility_types", "channels"):
        snap[k] = list(snap[k] or [])
    return snap


def explain(rule: AlertRule, row) -> dict:
    """Why was I alerted? Every condition the rule sets, with its threshold and the value observed for this event at
    evaluation time. A rule condition being met is not an established cause."""
    c: list[dict] = []
    fac = row["facility_name"] or "the nearest mapped facility"
    where = f"within {rule.repeat_within_m:.0f} m of {fac}" if rule.repeat_within_m else f"sharing {fac} as nearest facility"
    if rule.source_classes:
        c.append(_cond("classification", "Classification", " or ".join(rule.source_classes), row["classification"]))
    if rule.persistence_classes:
        c.append(_cond("persistence_class", "Persistence class", " or ".join(rule.persistence_classes), row["persistence_class"]))
    if rule.min_active_days is not None:
        c.append(_cond("persistence_days", "Active days (persistence)", f">= {rule.min_active_days}", row["days_active"]))
    if rule.min_priority is not None:
        c.append(_cond("priority", "Triage priority", f">= {rule.min_priority}", row["priority_score"]))
    if rule.min_confidence is not None:
        c.append(_cond("confidence", "Confidence score", f">= {rule.min_confidence}", row["confidence_score"]))
    if rule.min_frp is not None:
        c.append(_cond("frp", "Peak FRP (MW)", f">= {rule.min_frp}", row["frp_max"]))
    if rule.min_duration_hours is not None:
        c.append(_cond("duration", "Duration (hours)", f">= {rule.min_duration_hours}", row["duration_hours"]))
    if rule.min_evidence_stages is not None:
        c.append(_cond("evidence_stages", "Evidence stages available (not confidence)", f">= {rule.min_evidence_stages} of 13",
                       row["evidence_stages"]))
    if rule.facility_types:
        c.append(_cond("facility_type", "Facility type within distance", f"{', '.join(rule.facility_types)} within "
                       f"{rule.facility_within_m or 0:.0f} m", f"{row['fac_dist']:.0f} m" if row["fac_dist"] is not None else None))
    if rule.min_repeat_events is not None:
        c.append(_cond("repeated_activity", f"Events {where} in the last {rule.repeat_days} days",
                       f">= {rule.min_repeat_events} events / {rule.repeat_days} days", row["facility_events"]))
    if rule.activity_increase:
        w = rule.increase_window_days
        c.append(_cond("activity_increase", f"Events {where}: last {w} days vs the {w} days before",
                       f">= 3 and >= {rule.increase_factor:g} x previous period", row["fac_recent"], previous=row["fac_prior"]))
    if rule.center is not None:
        c.append(_cond("area", "Inside the rule area", f"within {rule.radius_m or 5000:.0f} m of the rule point", "inside"))
    if rule.watchlist_id is not None:
        c.append(_cond("watchlist", "Matches a watchlist item", "any item", "matched"))
    summary = "; ".join(f"{x['label']}: observed {x['observed']} (threshold {x['threshold']})" for x in c) or "All events matching the rule."
    if rule.activity_increase:
        summary = (f"Alert triggered because {row['fac_recent']} events were detected {where} during the last "
                   f"{rule.increase_window_days} days. Previous {rule.increase_window_days}-day count: {row['fac_prior']}.")
    elif rule.min_repeat_events is not None:
        summary = (f"Alert triggered because {row['facility_events']} events were detected {where} in the last "
                   f"{rule.repeat_days} days (threshold {rule.min_repeat_events}).")
    return {"rule": rule.name, "rule_id": str(rule.id), "rule_snapshot": rule_snapshot(rule),
            "conditions": c, "summary": summary, "result": "Rule condition met",
            "evaluated_at": datetime.now(UTC).isoformat(), "event": row["public_id"], "facility": row["facility_name"],
            "facility_distance_m": round(row["nearest_facility_distance_m"]) if row["nearest_facility_distance_m"] is not None else None,
            "evidence": {"classification": row["classification"], "confidence_state": row["confidence_state"],
                         "priority": row["priority_score"], "evidence_stages": row["evidence_stages"],
                         "last_detected": row["last_detected"].isoformat() if row["last_detected"] else None},
            "note": "The rule's condition is met. That is not an established cause and says nothing about the facility itself."}


_RESERVED_TLDS = (".local", ".localhost", ".invalid", ".test", ".example", ".internal", ".lan", ".home.arpa")
_RESERVED_DOMAINS = ("example.com", "example.org", "example.net")


def deliverable_address(email: str | None) -> bool:
    """False for addresses that can never receive mail (RFC 2606/6761 reserved names, local-only domains).
    Sending to them only produces bounces in the sender's mailbox."""
    domain = (email or "").rsplit("@", 1)[-1].lower().rstrip(".")
    if not domain or "." not in domain:
        return False
    return not (domain.endswith(_RESERVED_TLDS) or domain in _RESERVED_DOMAINS or any(domain.endswith("." + d) for d in _RESERVED_DOMAINS))


def in_cooldown(rule: AlertRule, now: datetime | None = None) -> bool:
    if not rule.cooldown_minutes or rule.last_notified_at is None:
        return False
    return (now or datetime.now(UTC)) - rule.last_notified_at < timedelta(minutes=rule.cooldown_minutes)


def _lock_rule(db: Session, rule: AlertRule) -> None:
    db.execute(select(AlertRule).where(AlertRule.id == rule.id).with_for_update())
    db.refresh(rule)


def deliver(db: Session, alert: Alert, rule: AlertRule) -> bool:
    """In-app delivery always happens. External channels (email/push) are suppressed while the
    rule is in cooldown; the suppression is recorded, never hidden. Returns whether anything was sent externally."""
    user = db.get(User, rule.owner_id)
    cooling = in_cooldown(rule)
    notified_externally = False
    for channel in rule.channels or ["in_app"]:
        status, error, recipient = "sent", None, None
        try:
            if channel != "in_app" and cooling:
                status = "skipped"
                error = f"cooldown: rule notified {rule.last_notified_at:%H:%M} UTC, window {rule.cooldown_minutes} min"
            elif channel == "in_app":
                recipient = str(user.id)
            elif channel == "email":
                recipient = user.email
                if not (settings.smtp_host and settings.smtp_from):
                    status, error = "skipped", "SMTP not configured"
                elif not deliverable_address(user.email):
                    status, error = "skipped", "undeliverable address (reserved or local domain)"
                else:
                    _send_email(user.email, alert)
            elif channel == "push":
                subs = db.execute(select(PushSubscription).where(PushSubscription.user_id == user.id)).scalars().all()
                if not (settings.vapid_private_key and settings.vapid_public_key):
                    status, error = "skipped", "Web Push (VAPID) not configured"
                elif not subs:
                    status, error = "skipped", "user has no push subscription"
                else:
                    recipient = f"{len(subs)} device(s)"
                    _send_push(subs, alert)
            else:
                status, error = "skipped", f"unknown channel {channel}"
        except Exception as exc:  # delivery failure is recorded, alert still exists in-app
            logger.exception("alert delivery failed (%s)", channel)
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        notified_externally |= channel != "in_app" and status == "sent"
        db.add(AlertDelivery(alert_id=alert.id, channel=channel, status=status, error=error, recipient=recipient))
    if notified_externally:
        rule.last_notified_at = alert.triggered_at or datetime.now(UTC)
    return notified_externally


def _send_email(to: str, alert: Alert) -> None:
    msg = EmailMessage()
    msg["Subject"] = f"[ThermalTrace] {alert.title}"
    msg["From"] = settings.smtp_from
    msg["To"] = to
    why = (alert.reason or {}).get("explanation") or {}
    conditions = "\n".join(f"  - {c['label']}: observed {c.get('observed')} (threshold {c.get('threshold')})"
                           for c in why.get("conditions", []))
    msg.set_content(
        f"{alert.title}\n\nSeverity: {alert.severity}\nRule: {why.get('rule') or (alert.reason or {}).get('rule')}\n"
        f"Why: {why.get('summary') or 'rule condition met'}\n{conditions}\n\n"
        "This alert reflects an automated classification. Confidence reflects the available evidence supporting the "
        "classification, not the probability of a fire; it is supporting evidence, not proof. An event is confirmed only "
        "after imagery confirmation or analyst review.")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(msg)


def _send_push(subs: list[PushSubscription], alert: Alert) -> None:
    from pywebpush import WebPushException, webpush

    payload = json.dumps({"title": "ThermalTrace alert", "body": alert.title, "event_id": str(alert.event_id)})
    sent, errors = 0, []
    for s in subs:  # one device failing does not stop delivery to the others
        try:
            webpush(subscription_info={"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}}, data=payload,
                    vapid_private_key=settings.vapid_private_key.get_secret_value(),
                    vapid_claims={"sub": settings.vapid_subject or "mailto:admin@example.org"})
            sent += 1
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (404, 410):  # the browser dropped this subscription: remove it
                object_session(s).delete(s)
            errors.append(f"HTTP {code}" if code else type(exc).__name__)
    if not sent and errors:
        raise RuntimeError(f"push failed on every device ({', '.join(errors)})")
