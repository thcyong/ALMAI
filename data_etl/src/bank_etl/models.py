"""PostgreSQL business tables, derived from the classification registry.

``configs/categories.yaml`` is the single source of truth: schemas, allowed
target tables, their columns, writer grains, date formats and views are all
built from it at import time. Adding a table, column, grain, date format or
dataset owner there is enough; removing objects is intentionally not automated.
The legacy ``finance.metric_value`` table is deliberately not managed here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml
from sqlalchemy import MetaData, Table

from bank_etl.field_types import SQL_TYPES, build_date_format

CONFIGS_ROOT = Path(__file__).resolve().parents[2] / "configs"
CATEGORIES_PATH = CONFIGS_ROOT / "categories.yaml"

business_metadata = MetaData()

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEFAULT_OWNER = "dashboard"


@dataclass(frozen=True)
class TargetTable:
    """One allowed write target; also the scope boundary for a dataset."""

    name: str
    table: Any
    grain: str
    dimension_column: str | None
    key_columns: tuple[str, ...]
    value_columns: tuple[str, ...]
    column_types: dict[str, str]
    owner_dataset: str = _DEFAULT_OWNER

    @property
    def allowed_columns(self) -> frozenset[str]:
        return frozenset((*self.key_columns, *self.value_columns))


@dataclass(frozen=True)
class Category:
    """One L2 table classification from the registry."""

    schema: str
    domain: str
    table: str
    subcategory: str
    grain: str
    dimension_column: str | None
    values: dict[str, str]
    owner_dataset: str = _DEFAULT_OWNER


@dataclass(frozen=True)
class CategoryRegistry:
    """Everything derived from the registry file; injectable in tests."""

    categories: tuple[Category, ...]
    views: tuple[tuple[str, str], ...]
    grains: tuple[str, ...]
    strategy_grain: dict[str, str]
    date_formats: dict[str, tuple[Callable[[Any], Any], bool]]


def load_categories(path: str | Path = CATEGORIES_PATH) -> CategoryRegistry:
    """Load and strictly validate the classification registry.

    No DB connection is used. Validation fails fast with a precise error so a
    bad registry can never silently produce a partial target model.
    """
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"Categories file not found: {source}")
    with source.open(encoding="utf-8") as stream:
        obj = yaml.safe_load(stream)
    if not isinstance(obj, dict) or "categories" not in obj:
        raise ValueError("categories.yaml must define a 'categories' list")
    if not isinstance(obj["categories"], list) or not obj["categories"]:
        raise ValueError("'categories' must be a non-empty list")

    owner_default = obj.get("owner_dataset", _DEFAULT_OWNER)
    if not isinstance(owner_default, str) or not _IDENTIFIER.fullmatch(owner_default):
        raise ValueError(f"unsafe owner_dataset {owner_default!r}")

    grains_raw = obj.get("grains") or ()
    if not isinstance(grains_raw, (list, tuple)):
        raise ValueError("'grains' must be a list of {name, strategy}")
    grains: list[str] = []
    strategy_grain: dict[str, str] = {}
    for index, item in enumerate(grains_raw):
        label = f"grain {index + 1}"
        if not isinstance(item, dict) or not item.get("name") or not item.get("strategy"):
            raise ValueError(f"{label}: must define 'name' and 'strategy'")
        name, strategy = str(item["name"]), str(item["strategy"])
        if not _IDENTIFIER.fullmatch(name) or not _IDENTIFIER.fullmatch(strategy):
            raise ValueError(f"{label}: unsafe grain/strategy name")
        if name in grains or strategy in strategy_grain:
            raise ValueError(f"{label}: duplicate grain or strategy")
        grains.append(name)
        strategy_grain[strategy] = name
    if not grains:
        raise ValueError("'grains' must declare at least one grain")

    date_formats_raw = obj.get("date_formats") or ()
    if not isinstance(date_formats_raw, dict):
        raise ValueError("'date_formats' must be a mapping")
    date_formats: dict[str, tuple[Callable[[Any], Any], bool]] = {}
    for name, spec in date_formats_raw.items():
        if not _IDENTIFIER.fullmatch(str(name)):
            raise ValueError(f"unsafe date_format name {name!r}")
        date_formats[str(name)] = build_date_format(spec, f"date format {name!r}")
    if not date_formats:
        raise ValueError("'date_formats' must declare at least one format")

    categories: list[Category] = []
    seen: set[str] = set()
    for index, raw in enumerate(obj["categories"]):
        label = f"category {index + 1}"
        if not isinstance(raw, dict):
            raise ValueError(f"{label}: must be a mapping")
        required = ("schema", "domain", "table", "subcategory", "grain", "values")
        missing = [key for key in required if key not in raw]
        if missing:
            raise ValueError(f"{label}: missing {sorted(missing)}")
        name = raw["table"]
        if not isinstance(name, str) or name.count(".") != 1:
            raise ValueError(f"{label}: table must be 'schema.table': {name!r}")
        schema, table_name = name.split(".", 1)
        if schema != raw["schema"]:
            raise ValueError(f"{label}: table prefix must match schema {raw['schema']!r}")
        for value, field in ((schema, "schema"), (table_name, "table name")):
            if not _IDENTIFIER.fullmatch(str(value)):
                raise ValueError(f"{label}: unsafe {field} {value!r}")
        if raw["grain"] not in grains:
            raise ValueError(f"{label}: grain {raw['grain']!r} is not declared in 'grains'")
        dimension = raw.get("dimension")
        if (raw["grain"] == "single_row") != (dimension is None):
            raise ValueError(
                f"{label}: 'dimension' must be set if and only if grain is an unpivot")
        if dimension is not None and not _IDENTIFIER.fullmatch(str(dimension)):
            raise ValueError(f"{label}: unsafe dimension {dimension!r}")
        values = raw["values"]
        if not isinstance(values, dict) or not values:
            raise ValueError(f"{label}: values must be a non-empty mapping")
        for column, pg_type in values.items():
            if not _IDENTIFIER.fullmatch(str(column)):
                raise ValueError(f"{label}: unsafe value column {column!r}")
            if pg_type not in SQL_TYPES:
                raise ValueError(f"{label}: unsupported type {pg_type!r} for {column!r}")
        if name in seen:
            raise ValueError(f"{label}: duplicate table {name!r}")
        seen.add(name)
        owner = str(raw.get("owner_dataset", owner_default))
        if not _IDENTIFIER.fullmatch(owner):
            raise ValueError(f"{label}: unsafe owner_dataset {owner!r}")
        if "owner_dataset" in raw and owner != raw["owner_dataset"]:
            raise ValueError(f"{label}: owner_dataset must be a plain identifier")
        categories.append(Category(
            schema=schema, domain=str(raw["domain"]), table=name,
            subcategory=str(raw["subcategory"]), grain=str(raw["grain"]),
            dimension_column=dimension, values=dict(values), owner_dataset=owner,
        ))

    views: list[tuple[str, str]] = []
    for index, raw in enumerate(obj.get("views") or ()):
        label = f"view {index + 1}"
        if not isinstance(raw, dict) or not raw.get("name") or not raw.get("sql"):
            raise ValueError(f"{label}: must define 'name' and 'sql'")
        views.append((str(raw["name"]), str(raw["sql"])))
    return CategoryRegistry(
        categories=tuple(categories), views=tuple(views),
        grains=tuple(grains), strategy_grain=strategy_grain,
        date_formats=date_formats,
    )


def build_targets(categories: tuple[Category, ...] | list[Category],
                  metadata: MetaData | None = None) -> dict[str, Any]:
    """Build SQLAlchemy targets from a validated category tuple."""
    from sqlalchemy import BigInteger, Column, Date, DateTime, Text, func

    meta = business_metadata if metadata is None else metadata
    targets: dict[str, TargetTable] = {}
    for category in categories:
        name = category.table
        schema, table_name = name.split(".", 1)
        columns = [Column("bank_id", BigInteger, primary_key=True),
                   Column("as_of_date", Date, primary_key=True)]
        types = {"bank_id": "BIGINT", "as_of_date": "DATE"}
        keys = ["bank_id", "as_of_date"]
        if category.dimension_column:
            columns.append(Column(category.dimension_column, Text, primary_key=True))
            types[category.dimension_column] = "TEXT"
            keys.append(category.dimension_column)
        for column_name, pg_type in category.values.items():
            declared = SQL_TYPES[pg_type]
            column_type = declared() if isinstance(declared, type) else declared
            columns.append(Column(column_name, column_type))
            types[column_name] = pg_type
        columns.append(Column("updated_at", DateTime(timezone=True), nullable=False,
                              server_default=func.now()))
        types["updated_at"] = "TIMESTAMPTZ"
        table = Table(table_name, meta, *columns, schema=schema)
        targets[name] = TargetTable(
            name=name, table=table, grain=category.grain,
            dimension_column=category.dimension_column,
            key_columns=tuple(keys), value_columns=tuple(category.values),
            column_types=types, owner_dataset=category.owner_dataset,
        )
    return targets


REGISTRY = load_categories()
CATEGORIES: tuple[Category, ...] = REGISTRY.categories
CATEGORY_VIEWS: tuple[tuple[str, str], ...] = REGISTRY.views
GRAINS: tuple[str, ...] = REGISTRY.grains
STRATEGY_GRAIN: dict[str, str] = REGISTRY.strategy_grain
DATE_FORMATS: dict[str, tuple[Callable[[Any], Any], bool]] = REGISTRY.date_formats
SCHEMAS: tuple[str, ...] = tuple(dict.fromkeys(c.schema for c in CATEGORIES))
CATEGORY_BY_TABLE: dict[str, Category] = {c.table: c for c in CATEGORIES}
TARGET_TABLES: dict[str, TargetTable] = build_targets(CATEGORIES)

# Backward-compatible alias used by older callers.
BANK_BASE_NII_EVE_VIEW: str = dict(CATEGORY_VIEWS)["risk.bank_base_nii_eve"]
