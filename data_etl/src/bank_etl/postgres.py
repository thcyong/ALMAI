"""PostgreSQL sink: transactional replacement of classified business tables."""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Mapping

from sqlalchemy import Engine, create_engine, delete, inspect, insert, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from bank_etl.config import DatasetSpec
from bank_etl.models import (CATEGORY_VIEWS, SCHEMAS, TARGET_TABLES,
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


def read_schema_snapshot(engine: Engine) -> dict[str, Any]:
    """Read the current database objects relevant to the registry."""
    inspector = inspect(engine)
    schemas = set(inspector.get_schema_names())
    tables: set[str] = set()
    columns: dict[str, set[str]] = {}
    for schema in SCHEMAS:
        for name in inspector.get_table_names(schema=schema):
            qualified = f"{schema}.{name}"
            tables.add(qualified)
            columns[qualified] = {col["name"] for col in
                                  inspector.get_columns(name, schema=schema)}
    return {"schemas": schemas, "tables": tables, "columns": columns}


def plan_schema_changes(snapshot: Mapping[str, Any],
                        targets: Mapping[str, Any] | None = None,
                        views: tuple[tuple[str, str], ...] | None = None) -> dict[str, Any]:
    """Diff the DB snapshot against the registry and return a concrete plan.

    No DDL is executed. ``targets``/``views`` default to the registry-derived
    globals, so tests can inject alternate registries. Adding a key/dimension
    column to an *existing* table changes its grain and cannot be done safely;
    it is reported as an error rather than applied. Value columns and views
    are additive and always safe.
    """
    active_targets = TARGET_TABLES if targets is None else targets
    active_views = CATEGORY_VIEWS if views is None else views
    existing_schemas = set(snapshot.get("schemas") or ())
    existing_tables = set(snapshot.get("tables") or ())
    existing_columns = snapshot.get("columns") or {}

    plan: dict[str, Any] = {
        "create_schemas": [s for s in SCHEMAS if s not in existing_schemas],
        "create_tables": [name for name in active_targets if name not in existing_tables],
        "targets": active_targets,
        "add_columns": [],
        "replace_views": [name for name, _ in active_views],
        "errors": [],
    }
    for name, target in active_targets.items():
        if name in existing_tables:
            present = set(existing_columns.get(name, ()))
            for column in target.key_columns:
                if column not in present:
                    plan["errors"].append(
                        f"{name}: key column {column!r} is missing from the existing "
                        "table; changing a table's grain requires a manual migration")
            for column in target.value_columns:
                if column not in present:
                    column_type = target.table.c[column].type.compile(
                        dialect=postgresql.dialect())
                    plan["add_columns"].append(
                        {"table": name, "column": column, "type": str(column_type)})
    if plan["errors"]:
        raise ValueError("Unsafe registry change detected: " + "; ".join(plan["errors"]))
    return plan


def apply_schema_plan(engine: Engine, plan: Mapping[str, Any],
                      views: tuple[tuple[str, str], ...] | None = None) -> dict[str, Any]:
    """Execute a plan produced by ``plan_schema_changes``; return a summary."""
    active_views = CATEGORY_VIEWS if views is None else views
    from sqlalchemy import Table as _Table

    if plan["create_schemas"]:
        with engine.begin() as conn:
            for schema in plan["create_schemas"]:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    if plan["create_tables"]:
        active_targets = plan.get("targets", TARGET_TABLES)
        tables: list[_Table] = [active_targets[name].table
                                for name in plan["create_tables"]]
        business_metadata.create_all(engine, tables=tables)
    with engine.begin() as conn:
        for item in plan["add_columns"]:
            conn.execute(text(
                f"ALTER TABLE {item['table']} ADD COLUMN IF NOT EXISTS "
                f"{item['column']} {item['type']}"))
        for _, view_sql in active_views:
            conn.execute(text(view_sql))
    return {
        "created_schemas": list(plan["create_schemas"]),
        "created_tables": list(plan["create_tables"]),
        "added_columns": list(plan["add_columns"]),
        "replaced_views": [name for name, _ in active_views],
    }


def init_database(engine: Engine) -> dict[str, Any]:
    """Detect and apply registry additions: schemas, tables, columns, views.

    The flow is explicit: read the current snapshot, plan the differences,
    then apply only additive changes. New tables and value columns take effect
    without code changes; key/dimension columns cannot be added to an existing
    table (that would change its grain) and raise a clear error. Nothing is
    dropped or altered in place, and the legacy ``finance.metric_value`` table
    is left untouched.
    """
    snapshot = read_schema_snapshot(engine)
    plan = plan_schema_changes(snapshot)
    return apply_schema_plan(engine, plan)


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
