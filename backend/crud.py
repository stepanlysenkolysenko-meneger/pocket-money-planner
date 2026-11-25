from decimal import Decimal

from sqlalchemy.orm import Session

import models, schemas
from database import decrypt_field, encrypt_field


def _decrypt_transaction(item: models.Transaction) -> models.Transaction:
    item.description = decrypt_field(item.description)
    item.receipt_data = decrypt_field(item.receipt_data)
    return item


def get_transactions(
    db: Session,
    scope: str = "personal",
    workspace_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
):
    query = db.query(models.Transaction).filter(models.Transaction.scope == scope)
    if workspace_id is not None:
        query = query.filter(models.Transaction.workspace_id == workspace_id)
    query = query.order_by(models.Transaction.date.desc(), models.Transaction.id.desc())
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return [_decrypt_transaction(item) for item in query.all()]


def create_transaction(db: Session, data: schemas.TransactionCreate):
    dump = data.model_dump()
    dump["description"] = encrypt_field(dump.get("description"))
    dump["receipt_data"] = encrypt_field(dump.get("receipt_data"))
    item = models.Transaction(**dump)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_transaction(db: Session, item: models.Transaction, data: schemas.TransactionUpdate):
    for key, value in data.model_dump().items():
        if key in {"description", "receipt_data"}:
            value = encrypt_field(value)
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item):
    db.delete(item)
    db.commit()


def get_goals(db: Session, scope: str = "personal"):
    return db.query(models.Goal).filter(models.Goal.scope == scope).order_by(models.Goal.created_at.desc()).all()


def create_goal(db: Session, data: schemas.GoalCreate):
    item = models.Goal(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_goal(db: Session, item: models.Goal, data: schemas.GoalUpdate):
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


def deposit_goal(db: Session, item: models.Goal, amount: Decimal):
    item.saved_amount += amount
    db.commit()
    db.refresh(item)
    return item
