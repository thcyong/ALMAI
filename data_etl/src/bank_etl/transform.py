"""Generic, registry-driven transforms (no per-field code)."""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from bank_etl.field_types import CONVERTERS, DATE_FORMATS, coerce_date, to_decimal
from bank_etl.mapping import FieldRule, FieldMapping
from bank_etl.models import TARGET_TABLES

_IDENTITY_COLUMNS = ("bank_id", "as_of_date")


def as_of_parameter(date_value: date, date_format: str,
                    formats: Mapping[str, tuple[Any, bool]] | None = None) -> Any:
    """Build the bound parameter for the configured as-of storage format."""
    registry = DATE_FORMATS if formats is None else formats
    spec = registry.get(date_format)
    if spec is None:
        raise ValueError(f"Unsupported date format: {date_format}")
    return spec[0](date_value)


def convert_value(value: Any, rule: FieldRule) -> Any:
    if value is None:
        return None
    converter = CONVERTERS.get(rule.pg_type)
    if converter is None:
        raise ValueError(f"Unsupported pg_type {rule.pg_type!r} for {rule.dev_field}")
    return converter(value, rule.dev_field)


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
