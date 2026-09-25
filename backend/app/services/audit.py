from fastapi import Request
from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.models.ops import AuditLog


def record(db: Session, request: Request | None, user_id, action: str, entity_type: str | None = None,
           entity_id=None, detail: dict | None = None) -> None:
    db.add(AuditLog(
        user_id=user_id, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id else None,
        detail=detail, ip=request.client.host if request and request.client else None, request_id=request_id_var.get(),
    ))
