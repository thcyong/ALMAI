"""PostgreSQL read executor for the Financial Query Service.

The SELECT statement is built exclusively from identifiers that come from the
validated Ontology mapping, and every filter / key value is a bound parameter.
No user-supplied SQL is concatenated. The query runs inside a read-only
transaction.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Engine, bindparam, column as sqla_column, create_engine
from sqlalchemy import select, table as sqla_table
from sqlalchemy.exc import SQLAlchemyError

from .models import DatabaseQueryError, sanitize_error


def get_engine(url: Optional[str] = None) -> Engine:
    """Create a SQLAlchemy engine from ``AI_POSTGRES_URL`` (reusing the ETL config).

    The URL is normalised to the ``psycopg`` driver, matching ``data_etl``.
    """
    url = url or os.getenv("AI_POSTGRES_URL")
    if not url:
        raise DatabaseQueryError(
            "PostgreSQL URL not configured (set AI_POSTGRES_URL or pass engine_url)")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url.startswith("postgresql+psycopg://"):
        raise DatabaseQueryError("AI_POSTGRES_URL must use postgresql+psycopg://")
    return create_engine(url, pool_pre_ping=True)


def execute_metric_query(mapping: dict[str, Any], bank_id: int, as_of_date: date,
                        engine: Optional[Engine] = None) -> list[Optional[Decimal]]:
    """Return the raw metric values (0, 1 or many rows) for a mapped concept.

    Safe by construction: table / column identifiers are quoted by SQLAlchemy
    Core; ``bank_id``, ``as_of_date`` and every mapping filter value are bound
    parameters. The connection is opened read-only.
    """
    if engine is None:
        engine = get_engine()
    table_name = mapping.get("table")
    column_name = mapping.get("column")
    filters = mapping.get("filters", {}) or {}
    if not table_name or table_name.count(".") != 1:
        raise DatabaseQueryError(f"invalid mapping table: {table_name!r}")
    schema, tbl = table_name.split(".")
    # Bind every column to the table so the FROM clause is emitted and
    # identifiers are correctly quoted; all values are bound parameters.
    t = sqla_table(tbl, schema=schema)
    col = sqla_column(column_name)
    stmt = select(col).select_from(t)
    params: dict[str, Any] = {"bank_id": bank_id, "as_of_date": as_of_date}
    stmt = stmt.where(sqla_column("bank_id") == bindparam("bank_id"))
    stmt = stmt.where(sqla_column("as_of_date") == bindparam("as_of_date"))
    for fk, fv in filters.items():
        params[fk] = fv
        stmt = stmt.where(sqla_column(fk) == bindparam(fk))
    try:
        with engine.connect().execution_options(readonly=True) as conn:
            rows = conn.execute(stmt, params).fetchall()
    except SQLAlchemyError as exc:
        raise DatabaseQueryError(sanitize_error(str(exc))) from exc
    return [row[0] for row in rows]
