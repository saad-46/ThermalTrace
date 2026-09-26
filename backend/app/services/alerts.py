"""Rule-based alerting. Rules are evaluated in SQL against changed events; each (rule, event)
pair alerts at most once. Every delivery attempt is recorded, including skipped channels."""
import json
import logging
import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ml.base import CLASS_LABELS
from app.models.auth import PushSubscription, User
from app.models.workflow import Alert, AlertDelivery, AlertRule

logger = logging.getLogger(__name__)

_MATCH_SQL = text(
    """
    SELECT e.id, e.public_id, e.classification, e.persistence_class, e.confidence_score, e.frp_max,
           e.duration_hours, e.admin_district, e.admin_state, e.latitude, e.longitude, e.priority_score,
           e.nearest_facility_id,
           (SELECT count(*) FROM thermal_events o WHERE e.nearest_facility_id IS NOT NULL
              AND o.nearest_facility_id = e.nearest_facility_id
              AND o.last_detected >= now() - make_interval(days => r.repeat_days)) AS facility_events,
           (SELECT count(*) FROM thermal_events o WHERE e.nearest_facility_id IS NOT NULL
              AND o.nearest_facility_id = e.nearest_facility_id AND o.first_detected >= now() - interval '7 days') AS fac_recent,
           (SELECT count(*) FROM thermal_events o WHERE e.nearest_facility_id IS NOT NULL
              AND o.nearest_facility_id = e.nearest_facility_id
              AND o.first_detected >= now() - interval '14 days' AND o.first_detected < now() - interval '7 days') AS fac_prior,
           (SELECT min(l.distance_m) FROM event_facility_links l JOIN facilities f ON f.id = l.facility_id
             WHERE l.event_id = e.id AND (cardinality(r.facility_types) = 0 OR f.facility_type = ANY(r.facility_types))) AS fac_dist
    FROM thermal_events e, alert_rules r
    WHERE r.id = :rule_id AND e.id = ANY(:ids) AND e.classification IS NOT NULL
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
      AND NOT EXISTS (SELECT 1 FROM alerts a WHERE a.rule_id = r.id AND a.event_id = e.id)
    """
)


def _severity(row) -> str:
    if row["classification"] == "industrial_fire" or (row["frp_max"] or 0) >= 100:
        return "critical"
    if row["persistence_class"] == "persistent" or (row["confidence_score"] or 0) >= 0.72:
        return "warning"
    return "info"


def evaluate_rules(db: Session, event_ids: list) -> dict:
    ids = [uuid.UUID(str(i)) for i in event_ids]
    if not ids:
        return {"alerts": 0}
    created = 0
    for rule in db.execute(select(AlertRule).where(AlertRule.is_active.is_(True))).scalars():
        for row in db.execute(_MATCH_SQL, {"rule_id": rule.id, "ids": ids}).mappings():
            if rule.facility_types and rule.facility_within_m is not None and (
                    row["fac_dist"] is None or row["fac_dist"] > rule.facility_within_m):
                continue
            if not repeat_and_increase_ok(rule, row["facility_events"], row["fac_recent"], row["fac_prior"]):
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
            }
            where = row["admin_district"] or f"{row['latitude']:.3f}, {row['longitude']:.3f}"
            alert = Alert(rule_id=rule.id, event_id=row["id"], user_id=rule.owner_id, severity=_severity(row),
                          title=f"{row['public_id']}: {label} ({row['persistence_class']}) — {where}", reason=reason)
            db.add(alert)
            db.flush()
            rule.last_triggered_at = alert.triggered_at
            deliver(db, alert, rule)
            created += 1
    db.commit()
    return {"alerts": created}


def repeat_and_increase_ok(rule: AlertRule, facility_events: int, recent: int, prior: int) -> bool:
    """Facility-activity conditions. Both are about the event's nearest mapped facility, so an event with
    no facility nearby never satisfies them. `activity_increase` needs at least 3 events in the last
    7 days and at least double the 7 days before, so one or two new events never count as a surge."""
    if rule.min_repeat_events is not None and (facility_events or 0) < rule.min_repeat_events:
        return False
    if rule.activity_increase and not ((recent or 0) >= 3 and (recent or 0) >= 2 * (prior or 0)):
        return False
    return True


def in_cooldown(rule: AlertRule, now: datetime | None = None) -> bool:
    if not rule.cooldown_minutes or rule.last_notified_at is None:
        return False
    return (now or datetime.now(UTC)) - rule.last_notified_at < timedelta(minutes=rule.cooldown_minutes)


def deliver(db: Session, alert: Alert, rule: AlertRule) -> None:
    """In-app delivery always happens. External channels (email/push) are suppressed while the
    rule is in cooldown; the suppression is recorded, never hidden."""
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


def _send_email(to: str, alert: Alert) -> None:
    msg = EmailMessage()
    msg["Subject"] = f"[ThermalTrace] {alert.title}"
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(
        f"{alert.title}\n\nSeverity: {alert.severity}\nReason: {json.dumps(alert.reason, indent=2)}\n\n"
        "This alert reflects an automated classification with the confidence shown; it is not a verified finding.")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(msg)


def _send_push(subs: list[PushSubscription], alert: Alert) -> None:
    from pywebpush import webpush

    payload = json.dumps({"title": "ThermalTrace alert", "body": alert.title, "event_id": str(alert.event_id)})
    for s in subs:
        webpush(subscription_info={"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}}, data=payload,
                vapid_private_key=settings.vapid_private_key.get_secret_value(),
                vapid_claims={"sub": settings.vapid_subject or "mailto:admin@example.org"})
