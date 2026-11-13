"""Strict, config-driven source field mapping.

The mapping file is the only definition of source fields and their targets.
Every target table/column is checked against the model Registry, so a mapping
can never introduce SQL by itself or silently overwrite another field.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bank_etl.models import TargetTable

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DIMENSION_CODE = re.compile(r"^[A-Za-z0-9_]+$")
_STRATEGY_GRAIN = {
    "direct": "single_row",
    "scenario_unpivot": "scenario_rows",
    "sector_unpivot": "sector_rows",
}
_REQUIRED_COLUMNS = ("dev_field", "source_alias", "target_table",
                     "target_column", "mapping", "dimension", "code", "pg_type")


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

    @property
    def by_dev_field(self) -> dict[str, FieldRule]:
        return {rule.dev_field: rule for rule in self.rules}

    @property
    def target_tables(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(rule.target_table for rule in self.rules))

    @property
    def strategy_counts(self) -> dict[str, int]:
        counts = {strategy: 0 for strategy in _STRATEGY_GRAIN}
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


def load_field_mapping(path: Path, allowed_aliases: set[str],
                       targets: dict[str, TargetTable]) -> FieldMapping:
    """Load and strictly validate a field mapping (no DB connection)."""
    if not path.is_file():
        raise ValueError(f"Mapping file not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        missing = [name for name in _REQUIRED_COLUMNS if name not in columns]
        if missing:
            raise ValueError(f"Mapping file missing columns: {sorted(missing)}")
        raw_rows = list(reader)
    if not raw_rows:
        raise ValueError("Mapping file must contain at least one field")

    rules: list[FieldRule] = []
    seen_fields: set[str] = set()
    seen_cells: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_rows):
        label = f"row {index + 2}"
        dev_field = (raw.get("dev_field") or "").strip()
        source_alias = (raw.get("source_alias") or "").strip()
        target_table = (raw.get("target_table") or "").strip()
        target_column = (raw.get("target_column") or "").strip()
        strategy = (raw.get("mapping") or "").strip()
        dimension = (raw.get("dimension") or "").strip()
        code = (raw.get("code") or "").strip()
        pg_type = (raw.get("pg_type") or "").strip()

        if not _IDENTIFIER.fullmatch(dev_field):
            raise ValueError(f"{label}: unsafe dev_field {dev_field!r}")
        if source_alias not in allowed_aliases:
            raise ValueError(f"{label}: source_alias {source_alias!r} is not a declared table alias")
        if strategy not in _STRATEGY_GRAIN:
            raise ValueError(f"{label}: unknown mapping strategy {strategy!r}")
        target = targets.get(target_table)
        if target is None:
            raise ValueError(f"{label}: target table {target_table!r} is not allowed")
        if target_column not in target.allowed_columns:
            raise ValueError(
                f"{label}: target column {target_table}.{target_column} is not allowed")
        if target.grain != _STRATEGY_GRAIN[strategy]:
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
            confidence=(raw.get("confidence") or "").strip(),
            notes=(raw.get("notes") or "").strip(),
        ))

    _validate_dimension_matrix(rules, targets)
    return FieldMapping(tuple(rules), path)


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
