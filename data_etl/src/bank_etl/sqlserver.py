"""Read-only SQL Server adapter with a mapping-driven, parameterised SQL builder."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import NoSuchTableError

from bank_etl.config import DatasetSpec, TableSpec, safe_identifier
from bank_etl.transform import as_of_parameter, coerce_date

RANGE_DATE_FORMATS = ("datetime", "date")


class MultipleSourceRecordsError(RuntimeError):
    """The configured business key does not uniquely identify a source row."""


def create_source_engine() -> Engine:
    """Create a read-only SQL Server connection using SQL authentication."""
    required = ["DEV_SQLSERVER_HOST", "DEV_SQLSERVER_DATABASE",
                "DEV_SQLSERVER_USER", "DEV_SQLSERVER_PASSWORD"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing SQL Server connection settings: {missing}")
    url = URL.create(
        "mssql+pyodbc",
        username=os.environ["DEV_SQLSERVER_USER"],
        password=os.environ["DEV_SQLSERVER_PASSWORD"],
        host=os.environ["DEV_SQLSERVER_HOST"],
        port=int(os.getenv("DEV_SQLSERVER_PORT", "1433")),
        database=os.environ["DEV_SQLSERVER_DATABASE"],
        query={
            "driver": os.getenv("DEV_SQLSERVER_DRIVER", "ODBC Driver 18 for SQL Server"),
            "Encrypt": "yes",
            "TrustServerCertificate": os.getenv("DEV_SQLSERVER_TRUST_CERTIFICATE", "no"),
            "ApplicationIntent": "ReadOnly",
        },
    )
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0,
                         connect_args={"timeout": 15})


def _table_sql(name: str) -> str:
    schema, table = name.split(".", 1)
    return f"{safe_identifier(schema)}.{safe_identifier(table)}"


def _date_condition(table: TableSpec, as_of: date) -> tuple[str, dict[str, Any]]:
    """Build the as-of filter for the configured storage format.

    DATETIME columns hold a timestamp, so the business calendar day is matched
    with a half-open range instead of an equality check.
    """
    column = table.as_of_date.sql()
    if table.date_format == "datetime":
        start = as_of_parameter(as_of, "datetime")
        return (f"{column} >= :asof_start AND {column} < :asof_next",
                {"asof_start": start, "asof_next": start + timedelta(days=1)})
    return f"{column} = :asof", {"asof": as_of_parameter(as_of, table.date_format)}


def _from_clause(table: TableSpec) -> list[str]:
    parts = [f"FROM {_table_sql(table.name)} AS {safe_identifier(table.alias)}"]
    for join in table.joins:
        parts.append(
            f"INNER JOIN {_table_sql(join.table)} AS {safe_identifier(join.alias)} "
            f"ON {join.left.sql()} = {join.right.sql()}"
        )
    return parts


def _build_query(spec: DatasetSpec, as_of: date) -> tuple[str, dict[str, Any]]:
    # One SELECT item per mapped source field. Aliases are generated internally
    # (f_N), never taken from user column names, so identically named columns on
    # different tables cannot collide.
    select_fields = ", ".join(
        f"{b.ref.sql()} AS {safe_identifier(b.output_alias)}" for b in spec.bindings
    )
    table = spec.table
    sql = [f"SELECT {select_fields}", *_from_clause(table)]
    conditions = [f"{table.bank_id.sql()} = :bank_id"]
    params: dict[str, Any] = {"bank_id": None}
    date_sql, date_params = _date_condition(table, as_of)
    conditions.append(date_sql)
    params.update(date_params)
    for index, (ref, value) in enumerate(table.where):
        name = f"where_{index}"
        conditions.append(f"{ref.sql()} = :{name}")
        params[name] = value
    sql.append("WHERE " + " AND ".join(conditions))
    return " ".join(sql), params


def build_query(spec: DatasetSpec, bank_id: int, as_of: date) -> tuple[str, dict[str, Any]]:
    """Return the parameterised SELECT plus its bound values for one request."""
    sql, params = _build_query(spec, as_of)
    params["bank_id"] = bank_id
    return sql, params


def read_source_rows(engine: Engine, spec: DatasetSpec, bank_id: int,
                     as_of: date) -> list[dict[str, Any]]:
    """Read all mapped columns for one bank/as-of snapshot (read-only)."""
    sql, params = build_query(spec, bank_id, as_of)
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]


def list_business_keys(engine: Engine, spec: DatasetSpec, start: date,
                       end: date, limit: int,
                       offset: int) -> list[tuple[int, date]]:
    """Page through distinct bank/as-of scopes in a stable, explicit range."""
    if limit < 1:
        raise ValueError("batch size must be positive")
    table = spec.table
    if table.date_format not in RANGE_DATE_FORMATS:
        raise ValueError(
            f"Backfill requires date_format in {RANGE_DATE_FORMATS}, "
            f"got {table.date_format!r}")
    as_of_column = table.as_of_date.sql()
    as_of_select = (f"CAST({as_of_column} AS DATE)"
                    if table.date_format == "datetime" else as_of_column)
    start_value = as_of_parameter(start, table.date_format)
    end_value = as_of_parameter(end + timedelta(days=1), table.date_format)
    sql = [f"SELECT DISTINCT {table.bank_id.sql()}, {as_of_select}",
           *_from_clause(table)]
    conditions = [f"{as_of_column} >= :range_start",
                  f"{as_of_column} < :range_end"]
    params: dict[str, Any] = {"range_start": start_value,
                              "range_end": end_value,
                              "page_offset": offset, "page_limit": limit}
    for index, (ref, value) in enumerate(table.where):
        name = f"where_{index}"
        conditions.append(f"{ref.sql()} = :{name}")
        params[name] = value
    sql.append("WHERE " + " AND ".join(conditions))
    sql.append("ORDER BY 1, 2 OFFSET :page_offset ROWS FETCH NEXT :page_limit ROWS ONLY")
    with engine.connect() as conn:
        rows = conn.execute(text(" ".join(sql)), params).all()
    return [(int(row[0]), coerce_date(row[1], "as_of_date")) for row in rows]


def _columns_by_alias(engine: Engine,
                      spec: DatasetSpec) -> dict[str, dict[str, str]]:
    inspector = inspect(engine)
    result: dict[str, dict[str, str]] = {}
    for name, alias in spec.table.tables:
        schema, table = name.split(".", 1)
        try:
            columns = inspector.get_columns(table, schema=schema)
        except NoSuchTableError:
            result[alias] = {}
            continue
        result[alias] = {str(c["name"]).casefold(): str(c["type"])
                         for c in columns}
    return result


def validate_source_schema(engine: Engine, spec: DatasetSpec) -> list[str]:
    """Compare the YAML/mapping contract with real SQL Server metadata."""
    columns_by_alias = _columns_by_alias(engine, spec)
    table_names = {alias: name for name, alias in spec.table.tables}
    problems: list[str] = []
    for alias, name in table_names.items():
        if not columns_by_alias[alias]:
            problems.append(
                f"table {name} (alias {alias!r}) is missing or invisible to this login; "
                "grant SELECT / VIEW DEFINITION")
    for ref in spec.all_refs:
        known = columns_by_alias.get(ref.alias)
        if not known:
            continue  # missing table already reported above
        if ref.column.casefold() not in known:
            problems.append(
                f"column {ref.ref!r} does not exist in {table_names[ref.alias]}")
    return problems


def report_source_schema_drift(engine: Engine,
                               spec: DatasetSpec) -> dict[str, object]:
    """Report Dev columns that are new, missing, or of a changed source type."""
    columns_by_alias = _columns_by_alias(engine, spec)
    extra: dict[str, list[str]] = {}
    missing: dict[str, list[str]] = {}
    source_types: dict[str, dict[str, str]] = {}
    for alias, columns in columns_by_alias.items():
        declared = {rule.dev_field.casefold()
                    for rule in spec.mapping.rules if rule.source_alias == alias}
        extra[alias] = sorted(set(columns) - declared)
        missing[alias] = sorted(declared - set(columns))
        source_types[alias] = {name: kind for name, kind in columns.items()
                               if name in declared}
    return {"extra_source_fields": extra, "missing_source_fields": missing,
            "source_types": source_types}


def inspect_source_schema(engine: Engine, spec: DatasetSpec) -> dict[str, object]:
    """Read actual source column names/types without changing the Dev database."""
    inspector = inspect(engine)
    result: dict[str, object] = {}
    for name, alias in spec.table.tables:
        schema, table = name.split(".", 1)
        try:
            columns = inspector.get_columns(table, schema=schema)
        except NoSuchTableError:
            result[alias] = {
                "table": name,
                "error": "not visible to this login; grant SELECT "
                         "(and VIEW DEFINITION for reflection)",
            }
            continue
        result[alias] = {
            "table": name,
            "columns": [{"name": str(c["name"]), "type": str(c["type"]),
                         "nullable": str(c["nullable"])} for c in columns],
        }
    return result
