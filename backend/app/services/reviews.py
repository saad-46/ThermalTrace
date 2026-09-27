"""Analyst workflow: decisions, notes, assignment. Decisions also form the training feedback dataset."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.models.auth import User
from app.models.ml import Classification
from app.models.thermal import ThermalEvent
from app.models.workflow import AnalystReview, Investigation, InvestigationNote
from app.schemas.api import AssignIn, NoteIn, ReviewIn

DECISION_TO_STATUS = {
    "confirm": "analyst_confirmed",
    "reclassify": "analyst_confirmed",
    "reject": "analyst_rejected",
    "false_positive": "false_positive",
    "escalate": "escalated",
    "mark_reviewed": "reviewed",  # looked at; no confirmation or rejection
    "request_evidence": "under_review",  # more evidence needed before a decision
}
# decisions that close the investigation (the others keep it open)
CLOSING = {"confirm", "reclassify", "reject", "false_positive", "mark_reviewed"}


def _event(db: Session, event_id: uuid.UUID) -> ThermalEvent:
    ev = db.get(ThermalEvent, event_id)
    if ev is None:
        raise NotFound("Event not found")
    return ev


def _investigation(db: Session, ev: ThermalEvent, user: User) -> Investigation:
    inv = db.execute(select(Investigation).where(Investigation.event_id == ev.id)).scalar_one_or_none()
    if inv is None:
        inv = Investigation(event_id=ev.id, opened_by=user.id, status="open", priority="normal")
        db.add(inv)
        db.flush()
    return inv


def record_review(db: Session, event_id: uuid.UUID, body: ReviewIn, user: User) -> AnalystReview:
    ev = _event(db, event_id)
    if body.decision == "reclassify" and not body.source_class:
        raise AppError("Reclassification requires a source_class", code="source_class_required")
    if body.decision == "false_positive" and not body.false_positive_reason:
        raise AppError("A false-positive decision requires a reason", code="reason_required")
    if body.decision in ("note", "request_evidence") and not body.notes:
        raise AppError("Say what is needed" if body.decision == "request_evidence" else "A note requires text", code="notes_required")
    current = db.execute(select(Classification).where(Classification.event_id == ev.id, Classification.is_current.is_(True))
                         ).scalar_one_or_none()
    label = body.source_class or (ev.classification if body.decision == "confirm" else None)
    review = AnalystReview(
        event_id=ev.id, user_id=user.id, decision=body.decision, source_class=label,
        persistence_class=body.persistence_class or (ev.persistence_class if body.decision == "confirm" else None),
        false_positive_reason=body.false_positive_reason, notes=body.notes, system_source_class=ev.classification,
        system_confidence_score=ev.confidence_score, classification_id=current.id if current else None,
    )
    review.previous_status = ev.review_status
    db.add(review)
    inv = _investigation(db, ev, user)
    if body.decision in DECISION_TO_STATUS:
        ev.review_status = DECISION_TO_STATUS[body.decision]
        if body.decision == "escalate":
            inv.status, inv.priority = "in_progress", "high"
        elif body.decision in CLOSING:
            inv.status, inv.closed_at = "closed", datetime.now(UTC)
        else:
            inv.status, inv.closed_at = "in_progress", None
    elif ev.review_status == "unreviewed":
        ev.review_status = "under_review"
        inv.status = "in_progress"
    review.new_status = ev.review_status
    db.flush()
    return review


def add_note(db: Session, event_id: uuid.UUID, body: NoteIn, user: User) -> InvestigationNote:
    ev = _event(db, event_id)
    note = InvestigationNote(event_id=ev.id, user_id=user.id, kind="attachment" if body.url else "note", body=body.body, url=body.url)
    db.add(note)
    inv = _investigation(db, ev, user)
    if ev.review_status == "unreviewed":
        ev.review_status = "under_review"
        inv.status = "in_progress"
    db.flush()
    return note


def assign(db: Session, event_id: uuid.UUID, body: AssignIn, user: User) -> Investigation:
    ev = _event(db, event_id)
    if body.user_id is not None:
        assignee = db.get(User, body.user_id)
        if assignee is None or not assignee.is_active or assignee.role == "viewer":
            raise AppError("Assignee must be an active analyst", code="invalid_assignee")
    inv = _investigation(db, ev, user)
    inv.assigned_to, inv.priority = body.user_id, body.priority
    ev.assigned_to = body.user_id
    if body.user_id and ev.review_status == "unreviewed":
        ev.review_status, inv.status = "under_review", "in_progress"
    db.flush()
    return inv
