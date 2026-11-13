"""PostgreSQL business tables and the target-table allow-list.

The 12 tables and their columns are declared here, in code, so field mappings
and writers can only address pre-declared targets. The legacy
``finance.metric_value`` table is deliberately not managed here: it stays in the
database until the separate drop migration is run.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (BigInteger, Column, Date, DateTime, MetaData, Numeric,
                        Table, Text, func)

SCHEMAS = ("core", "finance", "risk", "analysis")

business_metadata = MetaData()

_TYPES = {"NUMERIC": Numeric, "BIGINT": BigInteger, "DATE": Date, "TEXT": Text}


def _numeric(*names: str) -> dict[str, str]:
    return {name: "NUMERIC" for name in names}


# qualified name -> (writer grain, dimension column, value columns)
_TABLE_DEFS: dict[str, tuple[str, str | None, dict[str, str]]] = {
    "core.bank_snapshot": (
        "single_row", None, {"dashboard_source_id": "BIGINT"}),
    "finance.earnings": (
        "single_row", None,
        _numeric("margin", "roa", "roe", "non_ii", "non_ic", "non_int_cost",
                 "eff_mgn_tax", "roa_ex", "roe_ex")),
    "finance.funding": (
        "single_row", None,
        _numeric("loan2deposit", "nll2deposit", "nll2coredeposit",
                 "net_noncore_funding_dependence", "funding_cost")),
    "finance.capital": (
        "single_row", None,
        _numeric("tier1", "tier1_ratio", "tier1_risk_based_ratio",
                 "total_risk_based_ratio", "leverage", "leverage_asset")),
    "risk.liquidity": (
        "single_row", None,
        _numeric("st2asset", "sti2asset", "nll2asset", "lcr")),
    "risk.asset_quality": (
        "single_row", None, _numeric("cecl", "loss_rate", "alll")),
    "finance.balance_sheet_sector": (
        "sector_rows", "sector_code",
        _numeric("sector_value", "sector_face", "sector_duration",
                 "sector_gap_ratio", "sector_rate")),
    "risk.interest_rate_risk": (
        "single_row", None,
        _numeric("gap_ratio", "yield_curve_risk", "option_risk", "basis_risk",
                 "stress_eve", "stress_dynamic_gap", "stress_nii12",
                 "stress_efficiency_ratio", "ncua_base_eve_ratio",
                 "ncua_u300_eve_ratio", "ncua_duration", "krd_3m", "krd_1y",
                 "krd_3y", "krd_5y", "krd_7y", "krd_10y", "krd_20y",
                 "krd_30y", "gap_asset_nonsens")),
    "risk.interest_rate_scenario": (
        "scenario_rows", "scenario_code",
        _numeric("roe", "gap_ratio", "repricing_gap_ratio", "dynamic_gap",
                 "eve", "investments", "nii", "nii24", "ni", "ni24", "roe_ex",
                 "gap_rsal_ratio", "repricing_gap_rsal_ratio", "adj_nii",
                 "adj_nii24")),
    "finance.income_attribution": (
        "single_row", None,
        _numeric("ia_option_spread", "ia_cap_income", "ia_option_income",
                 "ia_oas_income", "ia_un_gain", "ia_nii")),
    "risk.loss_distribution": (
        "single_row", None,
        _numeric("par_beta_min", "par_beta_max", "par_beta_a", "par_beta_b",
                 "p95_loss", "p85_loss", "loss5_distance", "loss15_distance")),
    "analysis.camels": (
        "single_row", None,
        _numeric("score_c", "score_a", "score_m", "score_e", "score_l",
                 "score_s", "cfs_score_c", "cfs_score_a", "cfs_score_m",
                 "cfs_score_e", "cfs_score_l", "cfs_score_s")),
}

BANK_BASE_NII_EVE_VIEW = """CREATE OR REPLACE VIEW risk.bank_base_nii_eve AS
SELECT bank_id, as_of_date, nii, eve, updated_at
FROM risk.interest_rate_scenario
WHERE scenario_code = 'Base'"""


@dataclass(frozen=True)
class TargetTable:
    """One allowed write target; also the scope boundary for a dataset."""

    name: str
    table: Table
    grain: str
    dimension_column: str | None
    key_columns: tuple[str, ...]
    value_columns: tuple[str, ...]
    column_types: dict[str, str]
    owner_dataset: str = "dashboard"

    @property
    def allowed_columns(self) -> frozenset[str]:
        return frozenset((*self.key_columns, *self.value_columns))


def _build_target(name: str, grain: str, dimension_column: str | None,
                  values: dict[str, str]) -> TargetTable:
    schema, table_name = name.split(".", 1)
    columns = [Column("bank_id", BigInteger, primary_key=True),
               Column("as_of_date", Date, primary_key=True)]
    types = {"bank_id": "BIGINT", "as_of_date": "DATE"}
    keys = ["bank_id", "as_of_date"]
    if dimension_column:
        columns.append(Column(dimension_column, Text, primary_key=True))
        types[dimension_column] = "TEXT"
        keys.append(dimension_column)
    for column_name, pg_type in values.items():
        columns.append(Column(column_name, _TYPES[pg_type]))
        types[column_name] = pg_type
    columns.append(Column("updated_at", DateTime(timezone=True), nullable=False,
                          server_default=func.now()))
    types["updated_at"] = "TIMESTAMPTZ"
    table = Table(table_name, business_metadata, *columns, schema=schema)
    return TargetTable(name=name, table=table, grain=grain,
                       dimension_column=dimension_column,
                       key_columns=tuple(keys), value_columns=tuple(values),
                       column_types=types)


TARGET_TABLES: dict[str, TargetTable] = {
    name: _build_target(name, grain, dimension, values)
    for name, (grain, dimension, values) in _TABLE_DEFS.items()
}
