"""Strict YAML contracts for read-only SQL Server datasets.

A dataset is described by:

    dataset: dashboard
    mapping_file: dashboard_field_mapping.csv
    table: dbo.SomeTable            # single table shorthand
    # or
    table:
      name: dbo.MainTable
      alias: w
      join:
        - name: dbo.OtherTable
          alias: d
          on: [w.ForeignKey, d.ID]
      bank_id: w.BankID
      as_of_date: w.Asof
      date_format: datetime
      where: {w.RevisionID: 0}

Only validated identifiers are interpolated into SQL; every filter value is a
bound parameter. SELECT columns come exclusively from the mapping file and get
stable internal aliases (``f_N``), so identically named columns on different
tables never collide.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from bank_etl.mapping import FieldMapping, load_field_mapping
from bank_etl.models import TARGET_TABLES

_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONFIGS_ROOT = Path(__file__).resolve().parents[2] / "configs"


class _DatasetLoader(yaml.SafeLoader):
    """SafeLoader that only treats true/false as booleans and rejects duplicate keys.

    YAML 1.1 would otherwise turn the join key ``on:`` into the boolean True.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        self.flatten_mapping(node)
        result: dict = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError(
                    f"Non-string YAML key: {key!r} (line {key_node.start_mark.line + 1})")
            if key in result:
                raise ValueError(
                    f"Duplicate YAML key {key!r} (line {key_node.start_mark.line + 1})")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


_DatasetLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers
          if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_DatasetLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)

_DEFAULT_ALIAS = "t"
_DATE_FORMATS = ("datetime", "date", "yyyymmdd_int", "yyyymmdd_text", "iso_text")
_SQL_SNIPPETS = (";", "--", "/*", "*/")

DATASET_KEYS = {"dataset", "table", "mapping_file"}
TABLE_KEYS = {"name", "alias", "join", "bank_id", "as_of_date", "date_format", "where"}
JOIN_KEYS = {"name", "alias", "on"}


def safe_identifier(value: str) -> str:
    """Validate a trusted SQL Server identifier and bracket-quote it."""
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return f"[{value}]"


def _validate_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier for {label}: {value!r}")
    return value


def _split_table_name(value: Any, label: str = "table.name") -> str:
    """Normalise schema.table, defaulting the schema to dbo."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty 'schema.table' string")
    parts = value.split(".")
    if len(parts) == 1:
        parts = ["dbo", parts[0]]
    if len(parts) != 2:
        raise ValueError(f"{label} must be 'schema.table': {value!r}")
    return ".".join(_validate_identifier(p, label) for p in parts)


@dataclass(frozen=True)
class ColumnRef:
    """A validated ``alias.column`` reference."""

    alias: str
    column: str

    @property
    def ref(self) -> str:
        return f"{self.alias}.{self.column}"

    def sql(self) -> str:
        return f"{safe_identifier(self.alias)}.{safe_identifier(self.column)}"


def parse_column_ref(value: Any, default_alias: str, label: str = "column") -> ColumnRef:
    """Parse ``alias.column`` or a bare ``column`` using the default alias."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string: {value!r}")
    parts = value.split(".")
    if len(parts) == 1:
        return ColumnRef(default_alias, _validate_identifier(parts[0], label))
    if len(parts) != 2:
        raise ValueError(f"{label} must be 'alias.column': {value!r}")
    return ColumnRef(_validate_identifier(parts[0], label),
                     _validate_identifier(parts[1], label))


@dataclass(frozen=True)
class JoinSpec:
    """INNER JOIN to another table with a single equality condition."""

    table: str
    alias: str
    left: ColumnRef
    right: ColumnRef


@dataclass(frozen=True)
class TableSpec:
    """Where the rows come from: one main table plus optional inner joins."""

    name: str
    alias: str
    joins: tuple[JoinSpec, ...]
    bank_id: ColumnRef
    as_of_date: ColumnRef
    date_format: str
    where: tuple[tuple[ColumnRef, Any], ...]

    @property
    def tables(self) -> tuple[tuple[str, str], ...]:
        return ((self.name, self.alias), *((j.table, j.alias) for j in self.joins))

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(alias for _, alias in self.tables)


@dataclass(frozen=True)
class FieldBinding:
    """One SELECT item: internal alias -> source column."""

    output_alias: str
    ref: ColumnRef
    dev_field: str


@dataclass(frozen=True)
class DatasetSpec:
    """A dataset = one table source + one validated field mapping."""

    dataset_code: str
    table: TableSpec
    mapping: FieldMapping
    bindings: tuple[FieldBinding, ...]

    @property
    def all_refs(self) -> tuple[ColumnRef, ...]:
        """Every column referenced by the contract (for source schema validation)."""
        refs = [self.table.bank_id, self.table.as_of_date]
        refs += [b.ref for b in self.bindings]
        refs += [ref for ref, _ in self.table.where]
        for join in self.table.joins:
            refs += [join.left, join.right]
        return tuple(dict.fromkeys(refs))


def _parse_where(raw: Any, default_alias: str) -> tuple[tuple[ColumnRef, Any], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise ValueError("table.where must be a mapping of column -> literal value")
    conditions = []
    for key, value in raw.items():
        ref = parse_column_ref(key, default_alias, "table.where")
        if isinstance(value, bool):
            conditions.append((ref, value))
            continue
        if isinstance(value, (int, float)):
            conditions.append((ref, value))
            continue
        if isinstance(value, str):
            if any(token in value for token in _SQL_SNIPPETS):
                raise ValueError(f"table.where value looks like SQL: {value!r}")
            conditions.append((ref, value))
            continue
        raise ValueError(
            f"table.where value must be a bound scalar literal, not {type(value).__name__}")
    return tuple(conditions)


def _parse_join(raw: Any, declared: set[str]) -> JoinSpec:
    if not isinstance(raw, dict):
        raise ValueError("each table.join entry must be a mapping")
    unknown = set(raw) - JOIN_KEYS
    if unknown:
        raise ValueError(f"Unknown join keys: {sorted(unknown)}")
    table = _split_table_name(raw.get("name"), "table.join.name")
    alias = _validate_identifier(raw.get("alias"), "table.join.alias")
    if alias in declared:
        raise ValueError(f"Duplicate table alias: {alias!r}")
    on = raw.get("on")
    if not isinstance(on, (list, tuple)) or len(on) != 2:
        raise ValueError("table.join.on must be [left_alias.column, right_alias.column]")
    left = parse_column_ref(on[0], alias, "table.join.on")
    right = parse_column_ref(on[1], alias, "table.join.on")
    if left.alias not in declared:
        raise ValueError(f"join condition references unknown/undeclared alias: {left.alias!r}")
    if right.alias != alias:
        raise ValueError(
            f"join condition must reference the joined alias {alias!r}, got {right.alias!r}")
    return JoinSpec(table=table, alias=alias, left=left, right=right)


def _parse_table(raw: Any) -> TableSpec:
    if isinstance(raw, str):
        main = _split_table_name(raw)
        alias = _DEFAULT_ALIAS
        return TableSpec(
            name=main, alias=alias, joins=(),
            bank_id=ColumnRef(alias, "BankID"),
            as_of_date=ColumnRef(alias, "Asof"),
            date_format="datetime", where=(),
        )
    if not isinstance(raw, dict):
        raise ValueError("table must be a 'schema.table' string or a mapping")
    unknown = set(raw) - TABLE_KEYS
    if unknown:
        raise ValueError(f"Unknown table keys: {sorted(unknown)}")
    main = _split_table_name(raw.get("name"))
    alias = _validate_identifier(raw.get("alias", _DEFAULT_ALIAS), "table.alias")
    declared = {alias}
    joins = []
    for item in raw.get("join") or ():
        join = _parse_join(item, declared)
        declared.add(join.alias)
        joins.append(join)

    def ref(key: str, default: str) -> ColumnRef:
        return parse_column_ref(raw.get(key, default), alias, f"table.{key}")

    date_format = raw.get("date_format", "datetime")
    if date_format not in _DATE_FORMATS:
        raise ValueError(f"Unknown date_format: {date_format!r}; use one of {_DATE_FORMATS}")
    table = TableSpec(
        name=main, alias=alias, joins=tuple(joins),
        bank_id=ref("bank_id", "BankID"),
        as_of_date=ref("as_of_date", "Asof"),
        date_format=date_format,
        where=_parse_where(raw.get("where"), alias),
    )
    unknown_aliases = {
        r.alias for r in (table.bank_id, table.as_of_date, *(c for c, _ in table.where))
    } - set(table.aliases)
    if unknown_aliases:
        raise ValueError(f"Unknown table aliases: {sorted(unknown_aliases)}")
    return table


def _resolve_mapping_file(yaml_path: Path, value: Any) -> Path:
    """Only mapping files inside the project's configs directory are allowed."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("mapping_file is required and must be a relative path")
    raw = Path(value)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("mapping_file must stay inside the configs directory")
    root = _CONFIGS_ROOT.resolve()
    target = (yaml_path.parent / raw).resolve()
    if target != root and root not in target.parents:
        raise ValueError("mapping_file must be inside the configs directory")
    return target


def load_dataset(path: str | Path) -> DatasetSpec:
    """Load and strictly validate a YAML contract and its field mapping."""
    yaml_path = Path(path)
    with yaml_path.open(encoding="utf-8") as stream:
        obj = yaml.load(stream, Loader=_DatasetLoader)
    if not isinstance(obj, dict):
        raise ValueError("Dataset YAML must be a mapping")
    unknown = set(obj) - DATASET_KEYS
    if unknown:
        raise ValueError(f"Unknown dataset keys: {sorted(unknown)}")
    dataset_code = obj.get("dataset")
    if not isinstance(dataset_code, str) or not dataset_code.strip():
        raise ValueError("dataset is required and must be a non-empty string")
    if "table" not in obj:
        raise ValueError("table is required")
    table = _parse_table(obj["table"])
    mapping_path = _resolve_mapping_file(yaml_path, obj.get("mapping_file"))
    mapping = load_field_mapping(mapping_path, set(table.aliases), TARGET_TABLES)
    bindings = tuple(
        FieldBinding(output_alias=rule.output_alias,
                     ref=ColumnRef(rule.source_alias, rule.dev_field),
                     dev_field=rule.dev_field)
        for rule in mapping.rules
    )
    return DatasetSpec(dataset_code=dataset_code, table=table,
                       mapping=mapping, bindings=bindings)
