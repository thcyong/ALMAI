# ALMAI Dashboard Financial Business Table Design

Source file: `DashboardItems_202611090412(1).xlsx`, 331 source fields total, 257 non-null, 74 NULL.
Sample record: `ID=693257`, `BankID=-48858`, `asof=20260630`.

## Target Data Model

| PostgreSQL table | Financial business category | Source fields | Sample non-null |
|---|---|---:|---:|
| `core.bank_snapshot` | Banking Context / Base Information | 3 | 3 |
| `finance.earnings` | Profitability / Profitability Indicators | 9 | 9 |
| `finance.funding` | Funding Source / Funding Structure | 5 | 2 |
| `finance.capital` | Capital / Capital & Leverage | 6 | 6 |
| `risk.liquidity` | Liquidity Risk / Liquidity Indicators | 4 | 2 |
| `risk.asset_quality` | Credit & Asset Quality / Loss Provision | 3 | 3 |
| `finance.balance_sheet_sector` | Balance Sheet Structure / Sector Detail Rollup | 75 | 74 |
| `risk.interest_rate_risk` | Interest Rate Risk / Interest Rate Risk Rollup | 20 | 11 |
| `risk.interest_rate_scenario` | Interest Rate Risk / Interest Rate Scenario Results | 180 | 121 |
| `finance.income_attribution` | Profitability / Income Attribution | 6 | 6 |
| `risk.loss_distribution` | Model Risk & Loss / Loss Distribution & Model Parameters | 8 | 8 |
| `analysis.camels` | Bank Rating / CAMELS Model Score | 12 | 12 |

The 180 `indicator_scenario` columns are unpivoted into multiple rows of `risk.interest_rate_scenario` (bank_id, as_of_date, scenario_code); the 75 `Sector_attribute` columns are unpivoted into multiple rows of `finance.balance_sheet_sector` (bank_id, as_of_date, sector_code). The remaining 76 fields go into the banking-context and corresponding rollup tables respectively.

## Files and Execution Order

1. `dashboard_banking_schema.sql`: 12 PostgreSQL business tables + 1 Base NII/EVE query view; only creates objects, does not drop existing tables.
2. `dashboard_field_catalog.xlsx` / `dashboard_field_mapping.csv`: mapping, sample values, classification and financial-caliber to-be-confirmed items for all 331 columns.
3. `dashboard_sample_seed.sql`: a demo script that loads the Excel's single-row data into the new structure; requires the table-creation SQL to run first. **Demo data does not represent the latest Dev data.**

Usage: `psql -v ON_ERROR_STOP=1 -d <ai_database> -f dashboard_banking_schema.sql`, then run the seed in an isolated test database. Do not run the seed directly in production to replace real sync results.

## Important Design Judgments

- `finance.metric_value` is no longer used as the formal bank-classification storage target; **but the legacy table is not dropped yet**, until ALMAI's YAML, write layer and query layer switch over and are reconciled.
- The database is split into schemas by domain (`finance`, `risk`, `analysis`, `core`), with tables built by business entity/grain.
- All 12 tables currently keep only the latest state per business key, with no data history or Mapping Version added.
- `NUMERIC` avoids further truncating Excel financial raw values; the production ETL should read `Decimal` directly from Dev SQL Server.
- Source `ID` / BankID / asof are stored in `core.bank_snapshot`; financial classification tables are queried uniformly by `bank_id + as_of_date`.
- `NIIs_Base` / `EVEs_Base` in `risk.interest_rate_scenario` are mapped to `nii` / `eve` with `scenario_code='Base'`; the `risk.bank_base_nii_eve` view provides a simple query entry point.
- `NIIs_Base`, `AdjNIIs_Base`, `IA_NII`, `NII24s_Base` are all stored as independent fields and must not be merged.
- Abbreviations such as NLL/STI/RSAL/PaR/Ex/Adj/NCUA and the units of Ratio, Rate, Duration cannot be confirmed from a single Excel row.
- Some categories have business overlap: e.g., scenario NII can be used for profitability analysis, but to avoid duplicate storage it is classified under interest-rate-risk scenarios, and other businesses access it via views or JOINs.
- For some fields with unclear meaning, such as `GapAssetNonsens`, they are tentatively stored in the closest model-indicator table, and the mapping is marked `to_be_verified`; no financial formula is inferred from them.

## Minimal Changes for ALMAI Integration

The current `finance.metric_value` generic key-value write pattern cannot directly unpivot Sector/Scenario into multiple rows. It is recommended to keep the original `Config → SQL Server → Transform` and add a controlled target strategy at the output layer:

- `single_row`: fixed single-row bank-level rollup table, perform UPSERT;
- `sector_rows`: read the relevant Sector fields and replace the `(bank_id, as_of_date)` range within the same transaction;
- `scenario_rows`: read the series scenario fields and replace the corresponding range within the same transaction.

The three strategies reuse the same SQL Server query result, without needing to re-read Dashboard from Dev for each financial business table. In the future, adding a Dev bank-level rollup table in principle means adding YAML field mapping and target table definitions; multi-row details will add corresponding writers later, not forced into the above rollup tables.

## Migrating `finance.metric_value`

1. Back up the legacy table (and confirm no running jobs).
2. Run the table-creation SQL.
3. Refactor the ALMAI ETL to write the new classification tables transactionally.
4. Verify that NII/EVE and other important indicator values are consistent under `(bank_id, as_of_date)`, handling NULL, duplicate updates and missing scenarios.
5. Modify `show`, API, Agent tools and any SQL/View dependencies to switch to the new tables.
6. After the legacy table is decommissioned, have an authorized person run `DROP TABLE finance.metric_value;` separately.

The SQL generated this time **will not auto-delete legacy data** and will not directly connect to your PostgreSQL instance.
