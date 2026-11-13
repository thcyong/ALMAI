"""Date parameters, Decimal validation and generic mapping-driven transforms."""
from __future__ import annotations

import math
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from bank_etl.mapping import FieldRule, FieldMapping
from bank_etl.models import TARGET_TABLES

_IDENTITY_COLUMNS = ("bank_id", "as_of_date")


def as_of_parameter(date_value: date, date_format: str) -> Any:
    """Build the bound parameter for the configured as-of storage format."""
    if date_format == "datetime":
        return datetime.combine(date_value, time.min)
    if date_format == "date":
        return date_value
    if date_format == "yyyymmdd_int":
        return int(date_value.strftime("%Y%m%d"))
    if date_format == "yyyymmdd_text":
        return date_value.strftime("%Y%m%d")
    if date_format == "iso_text":
        return date_value.isoformat()
    raise ValueError(f"Unsupported date format: {date_format}")


def coerce_date(value: Any, label: str) -> date:
    """Normalise DATETIME / DATE / YYYYMMDD int / ISO text to a calendar date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        raise ValueError(f"Boolean is not a date: {label}")
    if isinstance(value, int):
        text = str(value)
        if len(text) == 8:
            return datetime.strptime(text, "%Y%m%d").date()
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date()
        if len(text) >= 10:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                pass
    raise ValueError(f"Unrecognised date value for {label}: {value!r}")


def to_decimal(value: Any, metric_code: str) -> Decimal | None:
    """Convert one source value to Decimal without any float arithmetic.

    NULL stays NULL and 0 stays 0. SQL Server FLOAT columns arrive as Python
    float; they are converted immediately through their shortest decimal
    representation, never used for intermediate calculation.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Boolean is not a financial number: {metric_code}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"Non-finite {metric_code}: {value!r}")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Non-numeric {metric_code}: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"Non-finite {metric_code}: {value!r}")
    return number


def convert_value(value: Any, rule: FieldRule) -> Any:
    if value is None:
        return None
    if rule.pg_type == "NUMERIC":
        return to_decimal(value, rule.dev_field)
    if rule.pg_type == "BIGINT":
        if isinstance(value, bool):
            raise ValueError(f"Boolean is not an integer: {rule.dev_field}")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Non-integer {rule.dev_field}: {value!r}") from exc
    if rule.pg_type == "DATE":
        return coerce_date(value, rule.dev_field)
    raise ValueError(f"Unsupported pg_type {rule.pg_type!r} for {rule.dev_field}")


def _verify_identity(rule: FieldRule, value: Any, bank_id: int,
                     as_of: date) -> None:
    expected: Any = bank_id if rule.target_column == "bank_id" else as_of
    if value != expected:
        raise ValueError(
            f"Source {rule.dev_field!r} ({value!r}) does not match "
            f"requested {rule.target_column} ({expected!r})")


def transform_dataset(record: Mapping[str, Any], mapping: FieldMapping,
                      bank_id: int, as_of: date) -> dict[str, list[dict[str, Any]]]:
    """Group one source record into rows per allowed target table.

    ``direct`` fills one row per single-row table; ``scenario_unpivot`` and
    ``sector_unpivot`` expand their dimension rows. Dimension rows are created
    from the mapping even when every value is NULL, so coverage stays verifiable.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for name, target in TARGET_TABLES.items():
        if target.grain == "single_row":
            rows = [{"bank_id": bank_id, "as_of_date": as_of}]
        else:
            rows = [{"bank_id": bank_id, "as_of_date": as_of,
                     target.dimension_column: code}
                    for code in mapping.dimensions(name)]
        grouped[name] = rows
        for row in rows:
            code = row[target.dimension_column] if target.dimension_column else ""
            index[(name, code)] = row

    for rule in mapping.rules:
        if rule.output_alias not in record:
            raise ValueError(f"Missing source field {rule.dev_field!r} in extracted row")
        value = convert_value(record[rule.output_alias], rule)
        if rule.target_column in _IDENTITY_COLUMNS:
            _verify_identity(rule, value, bank_id, as_of)
            continue
        index[(rule.target_table, rule.code)][rule.target_column] = value
    return grouped
