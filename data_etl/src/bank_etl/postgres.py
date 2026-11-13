"""PostgreSQL sink: transactional replacement of classified business tables."""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Mapping

from sqlalchemy import Engine, create_engine, delete, insert, select, text
from sqlalchemy.orm import Session

from bank_etl.config import DatasetSpec
from bank_etl.models import (BANK_BASE_NII_EVE_VIEW, SCHEMAS, TARGET_TABLES,
                             business_metadata)


def create_ai_engine() -> Engine:
    """Connect to AI PostgreSQL using a separate, scoped account."""
    url = os.getenv("AI_POSTGRES_URL")
    if not url:
        raise RuntimeError("Missing AI_POSTGRES_URL")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("AI_POSTGRES_URL must use postgresql+psycopg://")
    return create_engine(url, pool_pre_ping=True)


def init_database(engine: Engine) -> None:
    """Idempotently create the four schemas, the 12 tables and the base view.

    Existing tables (including the legacy finance.metric_value) are never
    altered or dropped here.
    """
    with engine.begin() as conn:
        for schema in SCHEMAS:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    business_metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(BANK_BASE_NII_EVE_VIEW))


def _scope_key(spec: DatasetSpec, bank_id: int, as_of: date) -> str:
    return f"{spec.dataset_code}:{bank_id}:{as_of.isoformat()}"


def replace_business_scope(session: Session, spec: DatasetSpec, bank_id: int,
                           as_of: date,
                           grouped: Mapping[str, list[dict[str, Any]]]) -> dict[str, int]:
    """Replace all 12 target tables for one bank/date inside the caller's transaction.

    A transaction-scoped advisory lock serialises concurrent syncs of the same
    scope. Every table is cleared and rewritten, so removed scenarios/sectors
    never leave stale rows. Any failure rolls the whole scope back.
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope_key))"),
        {"scope_key": _scope_key(spec, bank_id, as_of)},
    )
    written: dict[str, int] = {}
    for name, target in TARGET_TABLES.items():
        if target.owner_dataset != spec.dataset_code:
            raise ValueError(
                f"Dataset {spec.dataset_code!r} cannot write {name} "
                f"(owned by {target.owner_dataset!r})")
        rows = list(grouped.get(name, []))
        session.execute(
            delete(target.table).where(
                target.table.c.bank_id == bank_id,
                target.table.c.as_of_date == as_of,
            )
        )
        if rows:
            session.execute(insert(target.table), rows)
        written[name] = len(rows)
    return written


def read_business_scope(engine: Engine, spec: DatasetSpec, bank_id: int,
                        as_of: date) -> dict[str, list[dict[str, Any]]]:
    """Read raw rows of all 12 tables for one scope (for query/reconcile)."""
    result: dict[str, list[dict[str, Any]]] = {}
    with engine.connect() as conn:
        for name, target in TARGET_TABLES.items():
            rows = conn.execute(
                select(target.table).where(
                    target.table.c.bank_id == bank_id,
                    target.table.c.as_of_date == as_of,
                )
            ).mappings().all()
            result[name] = [dict(row) for row in rows]
    return result
