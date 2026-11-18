"""Tests for the config-driven, registry-based Dashboard sync.

    python -m unittest discover -s tests -v

PostgreSQL cases run only when AI_ETL_TEST_POSTGRES_URL points at a disposable
database; otherwise they are skipped.
"""
from __future__ import annotations

import os
import sys
import unittest
from collections import Counter
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock
from uuid import uuid4

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import MetaData, create_engine, delete, inspect, text

from bank_etl.config import load_dataset
from bank_etl.etl import sync_one
from bank_etl.field_types import to_bool, to_int, to_text
from bank_etl.models import (CATEGORIES, CATEGORY_BY_TABLE, SCHEMAS,
                             TARGET_TABLES, build_targets, load_categories)
from bank_etl.postgres import (init_database, plan_schema_changes,
                               read_business_scope)
from bank_etl.sqlserver import MultipleSourceRecordsError, build_query
from bank_etl.transform import (as_of_parameter, coerce_date, to_decimal,
                                transform_dataset)

BANK = -48858
ASOF = date(2026, 6, 30)
MAPPING_YAML = ROOT / "configs" / "dashboard_field_mapping.yaml"
CATEGORIES_YAML = ROOT / "configs" / "categories.yaml"

YAML_TEMPLATE = """dataset: dashboard
mapping_file: MAPPING_FILE
table:
  name: dbo.BankAnalyzingWatches
  alias: w
  join:
    - name: dbo.DashboardItems
      alias: d
      on: [w.DashboardID, d.ID]
  bank_id: w.BankID
  as_of_date: w.Asof
  date_format: datetime
  where:
    w.RevisionID: 0
"""


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return [dict(row) for row in self._rows]


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        return _Result(self._rows)


class FakeSource:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error

    def connect(self):
        if self.error:
            raise self.error
        return _Conn(self.rows)


def dashboard():
    return load_dataset(ROOT / "configs" / "dashboard.yaml")


def alias(spec, dev_field):
    return spec.mapping.by_dev_field[dev_field].output_alias


def full_record(spec, overrides=None, bank_id=BANK, as_of=ASOF):
    record = {rule.output_alias: None for rule in spec.mapping.rules}
    record[alias(spec, "ID")] = 693257
    record[alias(spec, "BankID")] = bank_id
    record[alias(spec, "asof")] = datetime.combine(as_of, datetime.min.time())
    for dev_field, value in (overrides or {}).items():
        record[alias(spec, dev_field)] = value
    return record


class _ConfigPair:
    def __enter__(self):
        name = uuid4().hex[:8]
        self.mapping = ROOT / "configs" / f"_test_{name}_mapping.yaml"
        self.yaml = ROOT / "configs" / f"_test_{name}_dataset.yaml"
        self.mapping.write_text(MAPPING_YAML.read_text(encoding="utf-8"),
                                encoding="utf-8")
        return self

    def load(self, yaml_text=None, mapping_text=None, *, categories=None, targets=None,
             strategy_grain=None):
        if mapping_text is not None:
            self.mapping.write_text(mapping_text, encoding="utf-8")
        text_value = (yaml_text or YAML_TEMPLATE).replace("MAPPING_FILE", self.mapping.name)
        self.yaml.write_text(text_value, encoding="utf-8")
        return load_dataset(self.yaml, categories=categories, targets=targets,
                            strategy_grain=strategy_grain)

    def __exit__(self, *exc):
        self.mapping.unlink(missing_ok=True)
        self.yaml.unlink(missing_ok=True)
        return False


def _mapping_lines(text):
    return text.splitlines()


def _flat_rows(path):
    """Expand a grouped mapping YAML into flat rows for count assertions."""
    with path.open(encoding="utf-8") as stream:
        obj = yaml.safe_load(stream)
    rows = []
    for group in obj["groups"]:
        inherited = {key: group[key] for key in
                     ("domain", "subcategory", "target_table", "mapping",
                      "dimension", "source_alias", "pg_type", "confidence")
                     if key in group}
        for field in group["fields"]:
            row = dict(inherited)
            row.update(field)
            rows.append(row)
    return rows


def field_count():
    return len(_flat_rows(MAPPING_YAML))


def mapping_counts(column):
    return Counter(str(row.get(column) or "").strip() for row in _flat_rows(MAPPING_YAML))


def expected_rows(spec):
    return sum(
        1 if target.grain == "single_row"
        else len(spec.mapping.dimensions(name))
        for name, target in TARGET_TABLES.items())


class ConfigTests(unittest.TestCase):
    def test_all_mapping_fields_are_loaded(self):
        spec = dashboard()
        self.assertEqual(len(spec.mapping.rules), field_count())
        self.assertEqual(len(spec.bindings), field_count())
        strategies = mapping_counts("mapping")
        self.assertEqual(spec.mapping.strategy_counts,
                         {name: strategies[name] for name in spec.mapping.strategy_counts})

    def test_dimensions_and_targets(self):
        spec = dashboard()
        self.assertEqual(set(spec.mapping.target_tables), set(TARGET_TABLES))
        self.assertEqual(len(spec.mapping.dimensions("risk.interest_rate_scenario")), 12)
        self.assertEqual(len(spec.mapping.dimensions("finance.balance_sheet_sector")), 15)
        self.assertEqual(len(spec.mapping.unconfirmed_fields),
                         mapping_counts("confidence")["to_be_verified"])

    def test_every_target_cell_is_allowlisted(self):
        spec = dashboard()
        for rule in spec.mapping.rules:
            target = TARGET_TABLES[rule.target_table]
            self.assertIn(rule.target_column, target.allowed_columns)
            self.assertEqual(rule.pg_type, target.column_types[rule.target_column])

    def test_source_aliases_match_the_two_dev_tables(self):
        spec = dashboard()
        counts = {a: 0 for a in spec.table.aliases}
        for rule in spec.mapping.rules:
            self.assertIn(rule.source_alias, counts)
            counts[rule.source_alias] += 1
        self.assertEqual(counts, {"w": 2, "d": 329})
        self.assertEqual(spec.mapping.by_dev_field["ID"].source_alias, "d")

    def test_mapping_file_must_stay_in_configs(self):
        for value in ("../data/dashboard_field_mapping.yaml", str(MAPPING_YAML)):
            with _ConfigPair() as pair:
                with self.assertRaises(ValueError):
                    pair.load(YAML_TEMPLATE.replace("MAPPING_FILE", value))

    def test_mapping_file_is_required(self):
        with _ConfigPair() as pair:
            with self.assertRaises(ValueError):
                pair.load(YAML_TEMPLATE.replace("mapping_file: MAPPING_FILE\n", ""))

    def test_duplicate_source_field_is_rejected(self):
        with _ConfigPair() as pair:
            lines = _mapping_lines(MAPPING_YAML.read_text(encoding="utf-8"))
            anchor = next(line for line in lines if "dev_field: Margin," in line)
            lines.insert(lines.index(anchor) + 1, anchor)
            with self.assertRaises(ValueError):
                pair.load(mapping_text="\n".join(lines) + "\n")

    def test_unknown_target_table_is_rejected(self):
        with _ConfigPair() as pair:
            text = MAPPING_YAML.read_text(encoding="utf-8").replace(
                "target_table: core.bank_snapshot", "target_table: raw.unknown_table", 1)
            with self.assertRaises(ValueError):
                pair.load(mapping_text=text)

    def test_wrong_pg_type_is_rejected(self):
        with _ConfigPair() as pair:
            text = MAPPING_YAML.read_text(encoding="utf-8").replace(
                "target_column: dashboard_source_id, pg_type: BIGINT",
                "target_column: dashboard_source_id, pg_type: NUMERIC", 1)
            with self.assertRaises(ValueError):
                pair.load(mapping_text=text)

    def test_incomplete_dimension_matrix_is_rejected(self):
        with _ConfigPair() as pair:
            lines = [line for line in _mapping_lines(
                MAPPING_YAML.read_text(encoding="utf-8"))
                if "dev_field: NIIs_D100," not in line]
            with self.assertRaises(ValueError):
                pair.load(mapping_text="\n".join(lines) + "\n")

    def test_new_mapping_field_needs_no_code_change(self):
        with _ConfigPair() as pair:
            text = MAPPING_YAML.read_text(encoding="utf-8").replace(
                "dev_field: Margin,", "dev_field: Margin_New,", 1)
            spec = pair.load(mapping_text=text)
            self.assertIn("Margin_New", spec.mapping.by_dev_field)
            record = full_record(spec, {"Margin_New": "0.125"})
            grouped = transform_dataset(record, spec.mapping, BANK, ASOF)
            self.assertEqual(grouped["finance.earnings"][0]["margin"], Decimal("0.125"))

    def test_domain_label_must_match_registry(self):
        with _ConfigPair() as pair:
            text = MAPPING_YAML.read_text(encoding="utf-8").replace(
                '  - domain: "Profitability"\n    subcategory: "Profitability Indicators"\n'
                '    target_table: finance.earnings',
                '  - domain: "Wrong Domain"\n    subcategory: "Profitability Indicators"\n'
                '    target_table: finance.earnings', 1)
            with self.assertRaises(ValueError):
                pair.load(mapping_text=text)

    def test_registry_column_expansion_needs_no_code_change(self):
        with _ConfigPair() as pair:
            category = CATEGORY_BY_TABLE["finance.earnings"]
            expanded = replace(
                category, values={**category.values, "extra_margin": "NUMERIC"})
            categories = tuple(
                expanded if item.table == category.table else item
                for item in CATEGORIES)
            registry = {item.table: item for item in categories}
            targets = build_targets(categories, MetaData())

            lines = _mapping_lines(MAPPING_YAML.read_text(encoding="utf-8"))
            anchor = next(line for line in lines
                          if "dev_field: Margin," in line)
            extra = anchor.replace("dev_field: Margin,", "dev_field: Margin_Extra,", 1)
            extra = extra.replace("target_column: margin,",
                                  "target_column: extra_margin,", 1)
            lines.insert(lines.index(anchor) + 1, extra)

            spec = pair.load(mapping_text="\n".join(lines) + "\n",
                             categories=registry, targets=targets)
            rule = spec.mapping.by_dev_field["Margin_Extra"]
            self.assertEqual(rule.target_column, "extra_margin")
            record = full_record(spec, {"Margin_Extra": "0.25"})
            grouped = transform_dataset(record, spec.mapping, BANK, ASOF)
            self.assertEqual(grouped["finance.earnings"][0]["extra_margin"],
                             Decimal("0.25"))


class SqlTests(unittest.TestCase):
    def test_all_mapped_columns_are_selected(self):
        spec = dashboard()
        sql, _ = build_query(spec, BANK, ASOF)
        self.assertEqual(sql.count(" AS [f_"), len(spec.bindings))
        self.assertIn("[d].[ID] AS [f_0]", sql)
        self.assertIn("[w].[BankID]", sql)
        self.assertIn("[w].[asof]", sql)

    def test_values_are_bound(self):
        sql, params = build_query(dashboard(), BANK, ASOF)
        self.assertIn(":bank_id", sql)
        self.assertIn(":where_0", sql)
        self.assertEqual(params["bank_id"], BANK)
        self.assertEqual(params["where_0"], 0)
        self.assertNotIn(str(BANK), sql)

    def test_datetime_uses_half_open_range(self):
        _, params = build_query(dashboard(), BANK, ASOF)
        self.assertEqual(params["asof_start"], datetime(2026, 6, 30))
        self.assertEqual(params["asof_next"], datetime(2026, 7, 1))


class TransformTests(unittest.TestCase):
    def test_rows_across_all_registry_tables(self):
        spec = dashboard()
        grouped = transform_dataset(full_record(spec), spec.mapping, BANK, ASOF)
        self.assertEqual(len(grouped), len(TARGET_TABLES))
        self.assertEqual(sum(len(rows) for rows in grouped.values()),
                         expected_rows(spec))
        self.assertEqual(len(grouped["risk.interest_rate_scenario"]), 12)
        self.assertEqual(len(grouped["finance.balance_sheet_sector"]), 15)

    def test_all_null_scenarios_are_kept(self):
        spec = dashboard()
        grouped = transform_dataset(full_record(spec), spec.mapping, BANK, ASOF)
        codes = {row["scenario_code"]
                 for row in grouped["risk.interest_rate_scenario"]}
        self.assertEqual(codes,
                         set(spec.mapping.dimensions("risk.interest_rate_scenario")))

    def test_decimal_null_zero_and_negative(self):
        self.assertIsNone(to_decimal(None, "x"))
        self.assertEqual(to_decimal(0, "x"), Decimal("0"))
        self.assertEqual(to_decimal(-1.25, "x"), Decimal("-1.25"))
        self.assertEqual(to_decimal(1.25, "x"), Decimal("1.25"))
        self.assertEqual(to_decimal("1.25", "x"), Decimal("1.25"))
        for bad in (True, "abc", float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                to_decimal(bad, "x")

    def test_scenario_and_sector_unpivot_are_not_shifted(self):
        spec = dashboard()
        record = full_record(spec, {
            "NIIs_Base": 11, "EVEs_Base": 12,
            "NIIs_U200": 21, "EVEs_U200": 22,
            "LoanSector_Value": 31, "DepositSector_Value": 41,
        })
        grouped = transform_dataset(record, spec.mapping, BANK, ASOF)
        scenarios = {r["scenario_code"]: r
                     for r in grouped["risk.interest_rate_scenario"]}
        self.assertEqual(scenarios["Base"]["nii"], Decimal("11"))
        self.assertEqual(scenarios["Base"]["eve"], Decimal("12"))
        self.assertEqual(scenarios["U200"]["nii"], Decimal("21"))
        self.assertEqual(scenarios["U200"]["eve"], Decimal("22"))
        self.assertIsNone(scenarios["D100"]["nii"])
        sectors = {r["sector_code"]: r
                   for r in grouped["finance.balance_sheet_sector"]}
        self.assertEqual(sectors["Loan"]["sector_value"], Decimal("31"))
        self.assertEqual(sectors["Deposit"]["sector_value"], Decimal("41"))

    def test_identity_mismatch_is_rejected(self):
        spec = dashboard()
        record = full_record(spec, {"BankID": -1})
        with self.assertRaises(ValueError):
            transform_dataset(record, spec.mapping, BANK, ASOF)

    def test_missing_source_field_is_rejected(self):
        spec = dashboard()
        record = full_record(spec)
        record.pop(alias(spec, "Margin"))
        with self.assertRaises(ValueError):
            transform_dataset(record, spec.mapping, BANK, ASOF)

    def test_invalid_number_reports_the_source_field(self):
        spec = dashboard()
        record = full_record(spec, {"Margin": "not-a-number"})
        with self.assertRaises(ValueError) as ctx:
            transform_dataset(record, spec.mapping, BANK, ASOF)
        self.assertIn("Margin", str(ctx.exception))

    def test_date_formats(self):
        self.assertEqual(as_of_parameter(ASOF, "yyyymmdd_int"), 20260630)
        self.assertEqual(as_of_parameter(ASOF, "iso_text"), "2026-06-30")
        self.assertEqual(coerce_date(20260630, "x"), ASOF)
        self.assertEqual(coerce_date("20260630", "x"), ASOF)
        self.assertEqual(coerce_date("2026-06-30T10:00:00", "x"), ASOF)
        self.assertEqual(coerce_date(datetime(2026, 6, 30, 10), "x"), ASOF)


@unittest.skipUnless(os.getenv("AI_ETL_TEST_POSTGRES_URL"),
                     "AI_ETL_TEST_POSTGRES_URL is not set")
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ["AI_ETL_TEST_POSTGRES_URL"]
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        cls.engine = create_engine(url)
        with cls.engine.begin() as conn:
            for schema in SCHEMAS:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            conn.execute(text("DROP VIEW IF EXISTS risk.bank_base_nii_eve"))
            for name in TARGET_TABLES:
                conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
        init_database(cls.engine)
        cls.spec = dashboard()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as conn:
            for target in TARGET_TABLES.values():
                conn.execute(delete(target.table))

    def sync(self, record=None, spec=None, bank_id=BANK, as_of=ASOF):
        spec = spec or self.spec
        return sync_one(FakeSource([record if record is not None
                                    else full_record(spec, bank_id=bank_id, as_of=as_of)]),
                        self.engine, spec, bank_id, as_of)

    def row_count(self):
        with self.engine.connect() as conn:
            return sum(conn.execute(text(f"SELECT count(*) FROM {name}")).scalar()
                       for name in TARGET_TABLES)

    def test_first_sync_writes_all_registry_tables(self):
        result = self.sync(full_record(self.spec, {
            "NIIs_Base": 1391523.6369047775, "EVEs_Base": 16382384.200495906}))
        rows = expected_rows(self.spec)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["tables"]), len(TARGET_TABLES))
        self.assertEqual(sum(result["tables"].values()), rows)
        self.assertEqual(self.row_count(), rows)
        self.assertEqual(result["base_nii_eve"]["nii"], "1391523.6369047775")

    def test_resync_replaces_without_accumulation(self):
        self.sync(full_record(self.spec, {"NIIs_Base": 1}))
        self.sync(full_record(self.spec, {"NIIs_Base": 2}))
        scope = read_business_scope(self.engine, self.spec, BANK, ASOF)
        scenarios = {row["scenario_code"]: row
                     for row in scope["risk.interest_rate_scenario"]}
        self.assertEqual(scenarios["Base"]["nii"], Decimal("2"))
        self.assertEqual(self.row_count(), expected_rows(self.spec))

    def test_failure_rolls_back_the_whole_scope(self):
        self.sync(full_record(self.spec, {"NIIs_Base": 11}))
        before = read_business_scope(self.engine, self.spec, BANK, ASOF)
        with self.assertRaises(RuntimeError):
            sync_one(FakeSource(error=RuntimeError("source down")),
                     self.engine, self.spec, BANK, ASOF)
        self.assertEqual(read_business_scope(self.engine, self.spec, BANK, ASOF),
                         before)
        with self.assertRaises(ValueError):
            self.sync(full_record(self.spec, {"Margin": "bad"}))
        self.assertEqual(read_business_scope(self.engine, self.spec, BANK, ASOF),
                         before)
        import bank_etl.etl as etl_module
        original = etl_module.replace_business_scope

        def fail_after_write(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("write failure after delete")

        with mock.patch.object(etl_module, "replace_business_scope", fail_after_write):
            with self.assertRaises(RuntimeError):
                self.sync(full_record(self.spec, {"NIIs_Base": 999}))
        self.assertEqual(read_business_scope(self.engine, self.spec, BANK, ASOF),
                         before)

    def test_scenario_and_sector_rows_are_not_shifted(self):
        self.sync(full_record(self.spec, {
            "NIIs_Base": 11, "NIIs_U200": 21,
            "LoanSector_Value": 31, "DepositSector_Value": 41}))
        scope = read_business_scope(self.engine, self.spec, BANK, ASOF)
        scenarios = {r["scenario_code"]: r
                     for r in scope["risk.interest_rate_scenario"]}
        sectors = {r["sector_code"]: r
                   for r in scope["finance.balance_sheet_sector"]}
        self.assertEqual(scenarios["Base"]["nii"], Decimal("11"))
        self.assertEqual(scenarios["U200"]["nii"], Decimal("21"))
        self.assertEqual(sectors["Loan"]["sector_value"], Decimal("31"))
        self.assertEqual(sectors["Deposit"]["sector_value"], Decimal("41"))

    def test_not_found_preserves_existing_data(self):
        self.sync(full_record(self.spec, {"NIIs_Base": 11}))
        before = read_business_scope(self.engine, self.spec, BANK, ASOF)
        result = sync_one(FakeSource([]), self.engine, self.spec, BANK, ASOF)
        self.assertEqual(result["status"], "not_found")
        self.assertTrue(result["preserved_existing_data"])
        self.assertEqual(read_business_scope(self.engine, self.spec, BANK, ASOF),
                         before)

    def test_multiple_source_rows_are_rejected(self):
        record = full_record(self.spec)
        with self.assertRaises(MultipleSourceRecordsError):
            sync_one(FakeSource([record, record]), self.engine, self.spec,
                     BANK, ASOF)
        self.assertEqual(self.row_count(), 0)

    def test_removed_dimension_leaves_no_stale_row(self):
        with _ConfigPair() as pair:
            lines = [line for line in _mapping_lines(
                MAPPING_YAML.read_text(encoding="utf-8"))
                if "dev_field: LoanSector_" not in line]
            spec = pair.load(mapping_text="\n".join(lines) + "\n")
            self.sync(full_record(self.spec), spec=self.spec)
            self.sync(full_record(spec), spec=spec)
            scope = read_business_scope(self.engine, spec, BANK, ASOF)
            self.assertEqual(len(scope["finance.balance_sheet_sector"]), 14)
            self.assertNotIn("Loan", {r["sector_code"] for r in
                                      scope["finance.balance_sheet_sector"]})

    def test_no_history_or_version_tables(self):
        inspector = inspect(self.engine)
        tables = {f"{schema}.{name}"
                  for schema in SCHEMAS
                  for name in inspector.get_table_names(schema=schema)}
        self.assertTrue(set(TARGET_TABLES).issubset(tables))
        self.assertFalse(any("version" in name or "history" in name
                             for name in tables))


class SchemaPlanTests(unittest.TestCase):
    """Schema detection/planner works without a live database."""

    def _full_snapshot(self):
        return {
            "schemas": set(SCHEMAS),
            "tables": set(TARGET_TABLES),
            "columns": {name: set(target.allowed_columns) | {"updated_at"}
                        for name, target in TARGET_TABLES.items()},
        }

    def test_no_changes_when_database_matches_registry(self):
        plan = plan_schema_changes(self._full_snapshot())
        self.assertEqual(plan["create_schemas"], [])
        self.assertEqual(plan["create_tables"], [])
        self.assertEqual(plan["add_columns"], [])
        self.assertEqual(len(plan["replace_views"]), 1)

    def test_new_schema_and_tables_are_planned(self):
        snapshot = {"schemas": set(), "tables": set(), "columns": {}}
        plan = plan_schema_changes(snapshot)
        self.assertEqual(plan["create_schemas"], list(SCHEMAS))
        self.assertEqual(plan["create_tables"], list(TARGET_TABLES))
        self.assertEqual(plan["add_columns"], [])

    def test_new_value_column_on_existing_table_is_planned(self):
        snapshot = self._full_snapshot()
        snapshot["columns"]["finance.earnings"].discard("roa")
        plan = plan_schema_changes(snapshot)
        self.assertEqual(plan["create_tables"], [])
        self.assertEqual([(c["table"], c["column"]) for c in plan["add_columns"]],
                         [("finance.earnings", "roa")])
        self.assertEqual(plan["add_columns"][0]["type"], "NUMERIC")

    def test_new_dimension_column_on_existing_table_is_rejected(self):
        snapshot = self._full_snapshot()
        snapshot["columns"]["risk.interest_rate_scenario"].discard("scenario_code")
        with self.assertRaises(ValueError) as ctx:
            plan_schema_changes(snapshot)
        self.assertIn("key column 'scenario_code' is missing", str(ctx.exception))

    def test_plan_carries_targets_for_apply(self):
        plan = plan_schema_changes(self._full_snapshot())
        self.assertIs(plan["targets"], TARGET_TABLES)


class RegistryExtensionTests(unittest.TestCase):
    """New types, grains, date formats and dataset owners need no code change."""

    def _registry(self, delimiter):
        text = CATEGORIES_YAML.read_text(encoding="utf-8")
        return text.replace(delimiter[0], delimiter[1], 1)

    def test_new_value_types_are_config_driven(self):
        registry = self._registry((
            '      adj_nii24: NUMERIC\n',
            '      adj_nii24: NUMERIC\n      extra_note: TEXT\n'
            '      extra_flag: BOOLEAN\n      extra_count: INTEGER\n'))
        cat = load_categories(self._write_registry(registry))
        targets = build_targets(cat.categories, MetaData())
        from bank_etl.field_types import CONVERTERS
        self.assertEqual(targets["risk.interest_rate_scenario"]
                         .column_types["extra_note"], "TEXT")
        self.assertIs(CONVERTERS["TEXT"], to_text)
        self.assertIs(CONVERTERS["BOOLEAN"], to_bool)
        self.assertIs(CONVERTERS["INTEGER"], to_int)

    def test_new_grain_is_config_driven(self):
        registry = self._registry((
            '  - name: sector_rows\n    strategy: sector_unpivot\n',
            '  - name: sector_rows\n    strategy: sector_unpivot\n'
            '  - name: product_rows\n    strategy: product_unpivot\n'))
        registry = registry.replace('grain: sector_rows', 'grain: product_rows', 1)
        cat = load_categories(self._write_registry(registry))
        self.assertEqual(cat.strategy_grain["product_unpivot"], "product_rows")
        with _ConfigPair() as pair:
            text = MAPPING_YAML.read_text(encoding="utf-8").replace(
                'mapping: sector_unpivot', 'mapping: product_unpivot', 1)
            spec = pair.load(mapping_text=text,
                             targets=build_targets(cat.categories, MetaData()),
                             categories={c.table: c for c in cat.categories},
                             strategy_grain=cat.strategy_grain)
            self.assertIn("product_unpivot", spec.mapping.strategy_counts)

    def test_custom_date_format_is_config_driven(self):
        registry = self._registry((
            '  datetime: {kind: datetime, range: true}\n',
            '  datetime: {kind: datetime, range: true}\n'
            '  compact_iso: {kind: strftime, format: "%Y%m%d", cast: str, range: false}\n'))
        cat = load_categories(self._write_registry(registry))
        self.assertIn("compact_iso", cat.date_formats)
        value = cat.date_formats["compact_iso"][0](ASOF)
        self.assertEqual(value, "20260630")
        from bank_etl.transform import as_of_parameter
        self.assertEqual(as_of_parameter(ASOF, "compact_iso", cat.date_formats),
                         "20260630")

    def test_owner_dataset_is_config_driven(self):
        registry = self._registry((
            'owner_dataset: dashboard\n', 'owner_dataset: risk_team\n'))
        cat = load_categories(self._write_registry(registry))
        targets = build_targets(cat.categories, MetaData())
        self.assertEqual(targets["finance.earnings"].owner_dataset, "risk_team")

    def _write_registry(self, text):
        path = ROOT / "configs" / f"_test_registry_{uuid4().hex[:8]}.yaml"
        path.write_text(text, encoding="utf-8")
        self.addCleanup(path.unlink, missing_ok=True)
        return path


if __name__ == "__main__":
    unittest.main()
