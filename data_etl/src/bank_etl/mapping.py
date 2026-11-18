"""Strict, config-driven source field mapping.

The mapping YAML is the only definition of source fields and their targets.
Every target table/column is checked against the model Registry, so a mapping
can never introduce SQL by itself or silently overwrite another field.

The file is organised as groups (one per target table) with inherited group
attributes; each group expands into flat field rules before validation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from bank_etl.models import (STRATEGY_GRAIN as _DEFAULT_STRATEGY_GRAIN,
                             Category, TargetTable)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DIMENSION_CODE = re.compile(r"^[A-Za-z0-9_]+$")
_GROUP_KEYS = ("domain", "subcategory", "target_table", "mapping", "dimension",
               "source_alias", "pg_type", "confidence", "notes")
_GROUP_REQUIRED = ("domain", "subcategory", "target_table", "mapping", "fields")
_FIELD_OVERRIDES = ("source_alias", "pg_type", "confidence", "notes",
                    "domain", "subcategory")


@dataclass(frozen=True)
class FieldRule:
    """One source column -> one target cell."""

    dev_field: str
    source_alias: str
    target_table: str
    target_column: str
    strategy: str
    dimension: str
    code: str
    pg_type: str
    output_alias: str
    confidence: str = ""
    notes: str = ""


@dataclass(frozen=True)
class FieldMapping:
    rules: tuple[FieldRule, ...]
    path: Path
    strategy_grain: dict[str, str] | None = None

    @property
    def strategies(self) -> dict[str, str]:
        return _DEFAULT_STRATEGY_GRAIN if self.strategy_grain is None else self.strategy_grain

    @property
    def by_dev_field(self) -> dict[str, FieldRule]:
        return {rule.dev_field: rule for rule in self.rules}

    @property
    def target_tables(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(rule.target_table for rule in self.rules))

    @property
    def strategy_counts(self) -> dict[str, int]:
        counts = {strategy: 0 for strategy in self.strategies}
        for rule in self.rules:
            counts[rule.strategy] += 1
        return counts

    def rules_for_table(self, name: str) -> tuple[FieldRule, ...]:
        return tuple(rule for rule in self.rules if rule.target_table == name)

    def dimensions(self, name: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            rule.code for rule in self.rules if rule.target_table == name))

    @property
    def unconfirmed_fields(self) -> tuple[FieldRule, ...]:
        return tuple(rule for rule in self.rules if rule.confidence == "to_be_verified")


def _read_yaml_rows(path: Path) -> list[dict[str, Any]]:
    """Expand a grouped mapping YAML into flat rule dictionaries."""
    with path.open(encoding="utf-8") as stream:
        obj = yaml.safe_load(stream)
    if not isinstance(obj, dict) or "groups" not in obj:
        raise ValueError("Mapping YAML must define a 'groups' list")
    groups = obj["groups"]
    if not isinstance(groups, list) or not groups:
        raise ValueError("'groups' must be a non-empty list")

    rows: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        label = f"group {index + 1}"
        if not isinstance(group, dict):
            raise ValueError(f"{label}: must be a mapping")
        missing = [key for key in _GROUP_REQUIRED if key not in group]
        if missing:
            raise ValueError(f"{label}: missing {sorted(missing)}")
        fields = group["fields"]
        if not isinstance(fields, list) or not fields:
            raise ValueError(f"{label}: 'fields' must be a non-empty list")
        inherited = {key: group[key] for key in _GROUP_KEYS if key in group}
        for field_index, field in enumerate(fields):
            field_label = f"{label} field {field_index + 1}"
            if not isinstance(field, dict):
                raise ValueError(f"{field_label}: must be a mapping")
            for key in ("dev_field", "target_column"):
                if key not in field:
                    raise ValueError(f"{field_label}: missing {key!r}")
            row = dict(inherited)
            for key in _FIELD_OVERRIDES:
                if key in field:
                    row[key] = field[key]
            row["dev_field"] = field["dev_field"]
            row["target_column"] = field["target_column"]
            row["code"] = field.get("code", "")
            rows.append(row)
    if not rows:
        raise ValueError("Mapping YAML must contain at least one field")
    return rows


def load_field_mapping(path: Path, allowed_aliases: set[str],
                       targets: dict[str, TargetTable],
                       categories: dict[str, Category] | None = None,
                       strategy_grain: dict[str, str] | None = None) -> FieldMapping:
    """Load and strictly validate a field mapping (no DB connection).

    When ``categories`` is supplied, each row's domain/subcategory labels must
    match the registry entry for its target table, so a mapping cannot silently
    drift away from the declared classification.
    """
    if not path.is_file():
        raise ValueError(f"Mapping file not found: {path}")
    raw_rows = _read_yaml_rows(path)
    strategies = _DEFAULT_STRATEGY_GRAIN if strategy_grain is None else strategy_grain

    rules: list[FieldRule] = []
    seen_fields: set[str] = set()
    seen_cells: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_rows):
        label = f"field {index + 1}"
        dev_field = str(raw.get("dev_field") or "").strip()
        source_alias = str(raw.get("source_alias") or "").strip()
        target_table = str(raw.get("target_table") or "").strip()
        target_column = str(raw.get("target_column") or "").strip()
        strategy = str(raw.get("mapping") or "").strip()
        dimension = str(raw.get("dimension") or "").strip()
        code = str(raw.get("code") or "").strip()
        pg_type = str(raw.get("pg_type") or "").strip()

        if not _IDENTIFIER.fullmatch(dev_field):
            raise ValueError(f"{label}: unsafe dev_field {dev_field!r}")
        if source_alias not in allowed_aliases:
            raise ValueError(f"{label}: source_alias {source_alias!r} is not a declared table alias")
        if strategy not in strategies:
            raise ValueError(f"{label}: unknown mapping strategy {strategy!r}")
        target = targets.get(target_table)
        if target is None:
            raise ValueError(f"{label}: target table {target_table!r} is not allowed")
        if categories is not None:
            category = categories.get(target_table)
            if category is None:
                raise ValueError(
                    f"{label}: target table {target_table!r} has no registry category")
            for field, expected in (("domain", category.domain),
                                    ("subcategory", category.subcategory)):
                actual = str(raw.get(field) or "").strip()
                if actual != expected:
                    raise ValueError(
                        f"{label}: {field} {actual!r} does not match registry "
                        f"{expected!r} for {target_table}")
        if target_column not in target.allowed_columns:
            raise ValueError(
                f"{label}: target column {target_table}.{target_column} is not allowed")
        if target.grain != strategies[strategy]:
            raise ValueError(
                f"{label}: strategy {strategy!r} does not match {target_table} grain {target.grain!r}")
        if strategy == "direct":
            if code:
                raise ValueError(f"{label}: direct mapping must not set code")
            if target.dimension_column:
                raise ValueError(f"{label}: direct mapping cannot target a dimensioned table")
        else:
            if dimension != target.dimension_column:
                raise ValueError(
                    f"{label}: dimension must be {target.dimension_column!r}, got {dimension!r}")
            if not _DIMENSION_CODE.fullmatch(code):
                raise ValueError(f"{label}: unsafe dimension code {code!r}")
        declared_type = target.column_types.get(target_column)
        if pg_type != declared_type:
            raise ValueError(
                f"{label}: pg_type {pg_type!r} does not match {target_table}."
                f"{target_column} ({declared_type!r})")
        if dev_field in seen_fields:
            raise ValueError(f"{label}: duplicate source field {dev_field!r}")
        cell = (target_table, target_column, code)
        if cell in seen_cells:
            raise ValueError(f"{label}: duplicate target cell {cell!r}")
        seen_fields.add(dev_field)
        seen_cells.add(cell)
        rules.append(FieldRule(
            dev_field=dev_field, source_alias=source_alias,
            target_table=target_table, target_column=target_column,
            strategy=strategy, dimension=dimension, code=code, pg_type=pg_type,
            output_alias=f"f_{index}",
            confidence=str(raw.get("confidence") or "").strip(),
            notes=str(raw.get("notes") or "").strip(),
        ))

    _validate_dimension_matrix(rules, targets)
    return FieldMapping(tuple(rules), path, strategy_grain=strategy_grain)


def _validate_dimension_matrix(rules: list[FieldRule],
                              targets: dict[str, TargetTable]) -> None:
    """Every dimension row must expose the same set of value columns."""
    for name, target in targets.items():
        if not target.dimension_column:
            continue
        by_code: dict[str, set[str]] = {}
        for rule in rules:
            if rule.target_table == name:
                by_code.setdefault(rule.code, set()).add(rule.target_column)
        if not by_code:
            continue
        expected = set(target.value_columns)
        for code, columns in by_code.items():
            if columns != expected:
                raise ValueError(
                    f"Incomplete dimension {name} code {code!r}: "
                    f"missing {sorted(expected - columns)}, extra {sorted(columns - expected)}")
