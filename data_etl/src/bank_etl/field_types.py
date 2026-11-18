"""Shared field-type and date-format registries.

A single source of truth for how a declared ``pg_type`` becomes a SQLAlchemy
column and how a source value is converted before writing. Adding a supported
type/format in ``categories.yaml`` needs no Python change; adding a genuinely
new type/format requires one entry in the tables below.
"""
from __future__ import annotations

import math
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, Text

# pg_type -> SQLAlchemy column type (used by models.build_targets).
SQL_TYPES: dict[str, Any] = {
    "NUMERIC": Numeric,
    "BIGINT": BigInteger,
    "INTEGER": Integer,
    "DATE": Date,
    "TIMESTAMP": DateTime(timezone=True),
    "TEXT": Text,
    "BOOLEAN": Boolean,
}


def to_decimal(value: Any, metric_code: str) -> Decimal | None:
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


def to_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Boolean is not an integer: {label}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Non-integer {label}: {value!r}") from exc


def coerce_date(value: Any, label: str) -> date | None:
    if value is None:
        return None
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


def to_timestamp(value: Any, label: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ValueError(f"Unrecognised timestamp value for {label}: {value!r}")


def to_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Boolean is not text: {label}")
    return value if isinstance(value, str) else str(value)


def to_bool(value: Any, label: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    raise ValueError(f"Non-boolean {label}: {value!r}")


# pg_type -> value converter, signature (value, label) -> Any.
CONVERTERS: dict[str, Callable[[Any, str], Any]] = {
    "NUMERIC": to_decimal,
    "BIGINT": to_int,
    "INTEGER": to_int,
    "DATE": coerce_date,
    "TIMESTAMP": to_timestamp,
    "TEXT": to_text,
    "BOOLEAN": to_bool,
}

# date_format -> (builder(date) -> bound parameter, supports range scan).
DATE_FORMATS: dict[str, tuple[Callable[[date], Any], bool]] = {
    "datetime": (lambda value: datetime.combine(value, time.min), True),
    "date": (lambda value: value, True),
    "yyyymmdd_int": (lambda value: int(value.strftime("%Y%m%d")), False),
    "yyyymmdd_text": (lambda value: value.strftime("%Y%m%d"), False),
    "iso_text": (lambda value: value.isoformat(), False),
}


def build_date_format(spec: dict[str, Any], label: str) -> tuple[Callable[[date], Any], bool]:
    """Build ``(date -> bound parameter, supports_range)`` from a YAML spec.

    Supported kinds: ``datetime``, ``date``, ``iso``, ``strftime`` (with a
    ``format`` string and optional ``cast``: ``str`` or ``int``). Any of them
    may declare ``range: true`` for backfill pagination.
    """
    if not isinstance(spec, dict):
        raise ValueError(f"{label}: date format spec must be a mapping")
    kind = spec.get("kind")
    cast = spec.get("cast", "str")
    if kind == "datetime":
        builder: Callable[[date], Any] = lambda value: datetime.combine(value, time.min)
    elif kind == "date":
        builder = lambda value: value
    elif kind == "iso":
        builder = lambda value: value.isoformat()
    elif kind == "strftime":
        pattern = spec.get("format")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError(f"{label}: strftime requires a 'format' string")
        if cast == "int":
            builder = lambda value: int(value.strftime(pattern))
        elif cast == "str":
            builder = lambda value: value.strftime(pattern)
        else:
            raise ValueError(f"{label}: unsupported cast {cast!r}")
    else:
        raise ValueError(f"{label}: unsupported date format kind {kind!r}")
    return builder, bool(spec.get("range", False))
