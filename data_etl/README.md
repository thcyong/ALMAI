# ALMAI Dashboard Financial Classification ETL

Dev SQL Server (read-only) → YAML + 331-field mapping → Decimal cleansing and classification conversion → 12 PostgreSQL business tables → JSON output.

Only the **latest** data is kept: the 12 tables for the same `BankID + AsOfDate` are replaced entirely within a single transaction, with no history retained. Adding a financial field only requires updating the mapping file (and extending the target table if necessary); the ETL main flow is unchanged.

## 1. Environment and Installation

- Python 3.11+; Dev uses a SQL Server account + password with `ApplicationIntent=ReadOnly`; the account needs `SELECT` on `dbo.BankAnalyzingWatches` and `dbo.DashboardItems`.
- Microsoft ODBC Driver 17/18; PostgreSQL 14+.
- Dependencies are declared in `pyproject.toml` (CLI script entry points removed).

Configure `DEV_SQLSERVER_*` and `AI_POSTGRES_URL` in `.env`; `.env` is already ignored by `.gitignore`. `configs/dashboard.yaml` points to `configs/dashboard_field_mapping.csv`, which is the single field definition.

## 2. Running

There are no command-line subcommands. The only entry point is `debug_run.py`, which syncs a fixed test bank/date:

```bash
cd data_etl
python debug_run.py            # or use VS Code F5 / Run Python File
```

The sync target is determined by constants at the top of `debug_run.py`:

```python
TEST_BANK_ID = -48858
TEST_AS_OF = date(2026, 6, 30)
```

Inside `sync`, tables are created idempotently before writing (schema, 12 business tables, the `risk.bank_base_nii_eve` view), so **tables are created automatically when missing** — no separate initialization step is needed; when a table already exists only `checkfirst` is performed and data is not altered. Output: `status`, `tables` (rows written per table, 37 in total), `base_nii_eve`.

The `data/` directory keeps the original design artifacts (`dashboard_banking_schema.sql`, `dashboard_field_catalog.xlsx`, `dashboard_design_notes.md`, `dashboard_sample_seed.sql`) for offline reference only; they are not the ETL data source.

## 3. YAML and Field Mapping

```yaml
dataset: dashboard
mapping_file: dashboard_field_mapping.csv

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
```

`mapping_file` is only allowed to point to a relative path inside the project's `configs/` directory (absolute paths and `..` are rejected). `configs/dashboard_field_mapping.csv` has these key columns:

| Column | Description |
|---|---|
| `dev_field` / `source_alias` | Source column name and owning table alias; 329 fields are in `d`, `BankID` / `asof` are in `w`, `ID` is explicitly bound to `d.ID` |
| `target_table` / `target_column` | Target table and column, must exist in the `models.py` whitelist |
| `mapping` | `direct` / `scenario_unpivot` / `sector_unpivot` |
| `dimension` / `code` | Dimension column (`scenario_code` / `sector_code`) and dimension value of the unpivoted table |
| `pg_type` | Target column type, verified column-by-column against the model at load time |
| `confidence` / `notes` | Financial-caliber to-be-confirmed markers (235 fields marked `to_be_verified`) |

Strict validation at load: 331 source fields are unique, target cells are unique, strategy matches table grain, the dimension matrix is complete (12 Scenario × 15 columns, 15 Sector × 5 columns), and identifiers are safe. `asof` is normalized from Dev's `DATETIME` to `DATE` and must match the requested date; a mismatch raises an error and writes nothing to PostgreSQL.

## 4. Four Schemas Classified by Financial Meaning

|---|---|
| `core` | Bank base information |
| `finance` | Bank finance, capital, funding and balance sheet |
| `risk` | Interest-rate risk, liquidity and other financial risks |
| `analysis` | CAMELS and other analysis results |

## 5. 12 Business Tables and Write Rules

| Table | Grain |
|---|---|
| `core.bank_snapshot` | single row |
| `finance.earnings` | single row |
| `finance.funding` | single row |
| `finance.capital` | single row |
| `finance.income_attribution` | single row |
| `finance.balance_sheet_sector` | 15 Sector rows |
| `risk.liquidity` | single row |
| `risk.asset_quality` | single row |
| `risk.interest_rate_risk` | single row |
| `risk.interest_rate_scenario` | 12 Scenario rows |
| `risk.loss_distribution` | single row |
| `analysis.camels` | single row |

12 tables in total: 10 single-row tables + `risk.interest_rate_scenario` + `finance.balance_sheet_sector`; one successful sync writes 37 rows. Even if a Scenario is all NULL, the row is kept for coverage verification.

Write rules:

- Dev query, per-record validation and Decimal conversion all happen outside the transaction; a source query failure never touches PostgreSQL.
- The 12 tables are cleared by `bank_id + as_of_date` and then written within the same PostgreSQL transaction; any table failure rolls back the whole; `pg_advisory_xact_lock` inside the transaction serializes concurrent syncs of the same business scope.
- `not_found` returns an explicit status and **keeps the existing records**, not treating a missing query as a source-side deletion.
- Each target table is tagged `owner_dataset = dashboard`; writes to the same table by other datasets are rejected to avoid cross-source overwrites.
- No financial recomputation: NULL, 0 and negative values are kept as-is — no absolute value, no percentage/unit conversion, no merging of different calibers such as `NIIs_Base`/`AdjNIIs_Base`/`IA_NII`/`NII24s_Base`.
- All numeric columns are `NUMERIC`; `FLOAT` sources are written with driver-visible decimal `Decimal(str(v))`, without claiming to recover precision that does not exist at source.

## 6. Tests

```bash
python -m unittest discover -s tests -v
```

`tests/test_etl.py` covers mapping validation, the 331-column SQL Builder, the three conversion strategies, Decimal/NULL/0/negative, identity consistency, the 12-table transaction and rollback, Scenario/Sector non-misalignment, and bank/date isolation with no history table. PostgreSQL cases run only when `AI_ETL_TEST_POSTGRES_URL` is set (must point to an isolated database; the test rebuilds the 12 tables per the current model), otherwise they are skipped.

## 7. Retiring the legacy `finance.metric_value`

The new ETL no longer reads or writes the legacy table, but **does not auto-delete** it. Follow this order:

1. Run `debug_run.py` once to create the 12 tables and view and sync the test bank.
2. Confirm the 12 tables have normal data (`base_nii_eve` is the `risk.bank_base_nii_eve` view).
3. Globally search whether CLI, API, views, or external jobs still reference `finance.metric_value` (including the legacy `finance.metric_definition`).
4. Backup: `pg_dump -t finance.metric_value --data-only <ai_database> > metric_value_backup.sql`.
5. Have an authorized person run `sql/drop_legacy_metric_value.sql` separately (it includes its own view-dependency and precondition guards).

## 8. To-Be-Confirmed and Limitations

- The financial caliber of 235 fields is marked `to_be_verified` (NLL, STI, RSAL, PaR, Ex, Adj, GapAssetNonsens, NCUA_*, Duration, Rate/Ratio units, etc.); currently only the original values are stored, with no interpretation or computation.
- `RevisionID` is fixed at 0; one `BankID + AsOfDate` may correspond to only one source record — multiple rows raise an error, and `TOP 1` is not used.
- Re-read by specified bank/date, not CDC; source-side deletions are not detected; no history version or Mapping Version is kept.
- `data/dashboard_sample_seed.sql` has only 9 Scenario rows (the design package omitted the all-NULL scenarios); the production ETL always produces the 12 rows defined by the mapping file.
