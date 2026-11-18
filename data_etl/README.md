# ALMAI Dashboard Financial Classification ETL

Read-only Dev SQL Server → three YAML contracts → strict validation → Decimal-safe, mapping-driven transform → atomic replacement of PostgreSQL business tables → JSON status.

Only the **latest** snapshot is kept: for one `bank_id + as_of_date`, all target tables are cleared and rewritten inside a single transaction, with no history. Every target object and every field mapping is configuration-driven: adding a table, column, grain, date format, dimension value or view requires **no Python change**.

## 1. Environment and Installation

- Python 3.11+; Dev uses SQL Server account + password with `ApplicationIntent=ReadOnly`; the account needs `SELECT` on the source tables (default: `dbo.BankAnalyzingWatches`, `dbo.DashboardItems`).
- Microsoft ODBC Driver 17/18; PostgreSQL 14+.
- Dependencies: `pyproject.toml` (SQLAlchemy 2.x, pyodbc, psycopg 3, PyYAML, python-dotenv). No CLI script entry points.

All connection settings live in the **single root `.env`** (git-ignored):

```
DEV_SQLSERVER_HOST=...      DEV_SQLSERVER_PORT=1433
DEV_SQLSERVER_DATABASE=...  DEV_SQLSERVER_DRIVER=ODBC Driver 17 for SQL Server
DEV_SQLSERVER_USER=...      DEV_SQLSERVER_PASSWORD=...
DEV_SQLSERVER_TRUST_CERTIFICATE=yes
AI_POSTGRES_URL=postgresql+psycopg://user:pw@host:5432/db
```

Every module loads that same root `.env` via `python-dotenv`, so F5 and CLI runs behave identically.

## 2. The Three YAML Files

| File | Loaded by | Responsibility |
|---|---|---|
| `configs/categories.yaml` | `models.py` | **Target model registry**: schemas, domains, tables, value columns/types, grains, date formats, dataset owner, views. Single source of truth. |
| `configs/dashboard_field_mapping.yaml` | `mapping.py` | **Source → target mapping**: grouped by target table; each field declares `dev_field`, `target_column`, optional `code` / overrides. |
| `configs/dashboard.yaml` | `config.py` | **Dataset contract**: which mapping file, Dev source table + JOINs, `bank_id` / `as_of_date` columns, date format, `where` filters, `dataset` code. |

Flow:

```
dashboard.yaml ──points to──> dashboard_field_mapping.yaml ──validated by──> categories.yaml
     │                                │                              │
  source SQL                    field → cell                  target schema
     └──────────── config.py ─────────┴──── mapping.py ───────────────┘
                                                      models.py (derive)
                                                           ↓
                                       init_database: detect → plan → apply
```

### 2.1 `categories.yaml`

Declares a three-level taxonomy:

- **schema** (L1 big category): e.g. `core`, `finance`, `risk`, `analysis`;
- **domain** (business group): e.g. `Interest Rate Risk`, `Profitability` (10 domains today);
- **table** (L2 small category): e.g. `risk.interest_rate_scenario`, with a `subcategory` label, a writer `grain` and typed `values`.

Also declares:

- `owner_dataset`: default owner of the tables (per-table override allowed);
- `grains`: writer grain ↔ mapping strategy pairs (`single_row`/`direct`, `scenario_rows`/`scenario_unpivot`, `sector_rows`/`sector_unpivot`); add a pair here to introduce a new grain;
- `date_formats`: source as-of storage formats — kinds `datetime`, `date`, `iso`, `strftime` (with `format` and `cast: str|int`); `range: true` marks a format usable for paged backfill;
- `views`: e.g. `risk.bank_base_nii_eve`.

At import, `models.py` derives `SCHEMAS`, `CATEGORY_BY_TABLE`, `TARGET_TABLES`, `STRATEGY_GRAIN`, `DATE_FORMATS`, `CATEGORY_VIEWS` from it. Supported column types are in `bank_etl/field_types.py`: `NUMERIC, BIGINT, INTEGER, DATE, TIMESTAMP, TEXT, BOOLEAN`, each with a matching value converter and SQLAlchemy column type.

### 2.2 `dashboard_field_mapping.yaml`

A **grouped YAML**: each group under `groups` holds table-level attributes inherited by its fields (per-field entries may override each one).

| Key | Level | Meaning |
|---|---|---|
| `domain`, `subcategory` | group | Must match the `categories.yaml` entry for `target_table` |
| `target_table` | group | Target table; must exist in the derived target registry |
| `mapping` | group | Strategy name declared under `grains` |
| `dimension`, `source_alias`, `pg_type`, `confidence`, `notes` | group or field | Inherited defaults; a field may override |
| `dev_field`, `target_column` | field | Source column and target column (required) |
| `code` | field | Dimension value (`scenario_code` / `sector_code`) for unpivot groups |

Minimal example:

```yaml
groups:
  - domain: "Interest Rate Risk"
    subcategory: "Interest Rate Scenario Results"
    target_table: risk.interest_rate_scenario
    mapping: scenario_unpivot
    dimension: scenario_code
    pg_type: NUMERIC
    fields:
      - {dev_field: NIIs_Base, target_column: nii, code: Base}
```

Strict load-time validation: unique `dev_field`, unique target cell `(table, column, code)`, strategy matches grain, complete dimension matrix (12 Scenario × 15 columns, 15 Sector × 5 columns), safe identifiers, `pg_type` matches the registry, and group labels match the registry. 331 fields are mapped today; 235 are marked `to_be_verified` in `confidence`.

### 2.3 `dashboard.yaml`

```yaml
dataset: dashboard
mapping_file: dashboard_field_mapping.yaml
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

`mapping_file` must be a relative path inside `configs/` (absolute paths and `..` are rejected). The custom YAML loader rejects duplicate keys and only treats literal `true/false` as booleans, so `on:` stays a string. Identifiers are regex-validated and bracket-quoted; every `where` value is a bound parameter (SQL-looking literals such as `;` or `--` are rejected). `asof` is normalised from Dev `DATETIME` to `DATE` using the configured `date_format` and must equal the requested date.

## 3. Running

No CLI subcommands; the only entry point is `debug_run.py` (VS Code **F5** works from any working directory):

```bash
cd data_etl
python debug_run.py
```

It loads the root `.env`, resolves all config paths relative to its own file, then syncs a fixed bank/date defined at the top:

```python
TEST_BANK_ID = -48599
TEST_AS_OF = date(2026, 6, 30)
```

`sync_one(source_engine, ai_engine, spec, bank_id, as_of)` runs:

1. `init_database(ai_engine)` — detect and apply schema additions (see §4);
2. `read_source_rows(...)` — parameterised `SELECT` with internal aliases `f_0 … f_N`;
3. if more than one source row → `MultipleSourceRecordsError`; if none → `status: "not_found"` and existing data is left intact;
4. `transform_dataset(...)` — Decimal-safe, mapping-driven expansion into per-table rows;
5. one transaction replacing all target tables for that scope.

Returned JSON includes `status`, `dataset`, `bank_id`, `as_of_date`, `source_fields`, `tables` (rows written per table; 37 today), `base_nii_eve` (Base scenario `nii`/`eve`), and `preserved_existing_data`.

The `data/` directory holds original design artifacts (`dashboard_banking_schema.sql`, `dashboard_field_catalog.xlsx`, `dashboard_design_notes.md`, `dashboard_sample_seed.sql`, plus an older `dashboard_field_mapping.csv`) for offline reference only — they are **not** ETL inputs and are not updated automatically.

## 4. Automatic Schema Detection (`init_database`)

`postgres.py` uses an explicit **detect → plan → apply** flow:

1. `read_schema_snapshot(engine)` — inspect current schemas, tables, columns;
2. `plan_schema_changes(snapshot)` — diff against the registry, producing `create_schemas`, `create_tables`, `add_columns` (with PostgreSQL-rendered types) and `replace_views`;
3. `apply_schema_plan(engine, plan)` — `CREATE SCHEMA IF NOT EXISTS`, `create_all(tables=missing)`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE OR REPLACE VIEW`.

It returns a report such as:

```python
{"created_schemas": [...], "created_tables": [...],
 "added_columns": [{"table": "finance.earnings", "column": "roa", "type": "NUMERIC"}],
 "replaced_views": ["risk.bank_base_nii_eve"]}
```

Safety boundaries:

- **Automatic**: new schemas, new tables, new value columns, view definition changes.
- **Rejected with an error**: adding a key/dimension column to an existing table (changes its grain — needs a manual migration).
- **Never automatic**: dropping tables/columns, changing column types (non-destructive by design). The legacy `finance.metric_value` table is untouched.
- Each table's `owner_dataset` is enforced on write: a dataset may only write tables it owns.

## 5. Classification Model

Four schemas classify data by financial meaning:

| Schema | Meaning |
|---|---|
| `core` | Bank base information |
| `finance` | Earnings, funding, capital, income attribution, balance-sheet sectors |
| `risk` | Interest-rate risk, liquidity, asset quality, loss distribution |
| `analysis` | CAMELS and other analysis results |

12 business tables today: 10 single-row tables + `risk.interest_rate_scenario` (12 Scenario rows) + `finance.balance_sheet_sector` (15 Sector rows). All-NULL dimension rows are still written for coverage verification.

## 6. Write Rules and Safety

- `init_database` runs before the source query, so a fresh database is created even when the source has no data; business data is only touched after a successful query and transform.
- Dev query, validation and Decimal conversion happen outside the data transaction; a query/validation failure never writes business rows.
- All target tables are cleared by `bank_id + as_of_date` then rewritten in one PostgreSQL transaction; any failure rolls the whole scope back. `pg_advisory_xact_lock` serialises concurrent syncs of the same scope.
- `not_found` returns an explicit status and **preserves existing records** — a missing source row is not treated as a deletion.
- No financial recomputation: `NULL`, `0` and negatives are kept as-is; no absolute values, no unit/percentage conversion, no merging of different calibers (`NIIs_Base` / `AdjNIIs_Base` / `IA_NII` / `NII24s_Base`, etc.).
- Numeric columns use `NUMERIC`; SQL Server `FLOAT` values are written as `Decimal(str(v))` without claiming recovered precision.
- Source-schema drift helpers (read-only): `validate_source_schema`, `report_source_schema_drift`, `inspect_source_schema`, and `list_business_keys` for paged backfill.

## 7. Extending Without Code Changes

| Goal | Change |
|---|---|
| New schema or table | Add a `categories` entry in `categories.yaml` + a group in the mapping YAML; next sync creates the schema/table |
| New column on an existing table | Add it to the table's `values` in `categories.yaml` + a field in the mapping group; next sync runs `ADD COLUMN IF NOT EXISTS` |
| New dimension value (scenario/sector code) | Add `code` rows in the mapping YAML, completing **all** value columns for that code |
| New grain / strategy | Add a `grains` pair in `categories.yaml` |
| New date storage format | Add a `date_formats` entry in `categories.yaml` (strftime patterns supported) |
| New view | Add a `views` entry in `categories.yaml` |
| New dataset owner | Set `owner_dataset` (top level or per table) and match it in `dashboard.yaml: dataset` |
| New Dev table / JOIN | Edit `dashboard.yaml: table.name / join / bank_id / as_of_date / where` |

Remaining Python-level boundaries (change once, then configuration again):

- a genuinely new column type not in the 7 supported types → add a converter in `field_types.py`;
- a date encoding not expressible with `strftime` → add a kind in `build_date_format`;
- a grain with semantics beyond "single row" vs "expand by dimension" → extend `transform_dataset`;
- dropping/renaming objects or changing grain of an existing table → manual migration (by design).

## 8. Tests

```bash
python -m unittest discover -s tests -v
```

41 tests cover: config and mapping validation, registry extension (new types/grains/date formats/owner), schema detect/plan, the 331-column SQL builder, the three conversion strategies, Decimal/NULL/0/negative, identity consistency, the 12-table transaction and rollback, Scenario/Sector non-misalignment, and bank/date isolation with no history table. PostgreSQL cases run only when `AI_ETL_TEST_POSTGRES_URL` is set (must point to an isolated database; the test rebuilds the tables from the current registry), otherwise they are skipped (8 skipped locally).

## 9. Retiring the legacy `finance.metric_value`

The new ETL no longer reads or writes the legacy table, but **does not auto-delete** it. Follow this order:

1. Run `debug_run.py` once to create the 12 tables and view and sync the test bank.
2. Confirm the 12 tables have normal data (`base_nii_eve` is the `risk.bank_base_nii_eve` view).
3. Globally search whether CLI, API, views, or external jobs still reference `finance.metric_value` (including the legacy `finance.metric_definition`).
4. Backup: `pg_dump -t finance.metric_value --data-only <ai_database> > metric_value_backup.sql`.
5. Have an authorized person run `sql/drop_legacy_metric_value.sql` separately (it includes its own view-dependency and precondition guards).

## 10. To-Be-Confirmed and Limitations

- The financial caliber of 235 fields is marked `to_be_verified` (NLL, STI, RSAL, PaR, Ex, Adj, GapAssetNonsens, NCUA_*, Duration, Rate/Ratio units, etc.); only original values are stored, with no interpretation or computation.
- `RevisionID` is fixed at 0; one `BankID + AsOfDate` may correspond to only one source row — multiple rows raise an error, and `TOP 1` is not used.
- Re-read by specified bank/date, not CDC; source-side deletions are not detected; no history or Mapping Version is kept.
- `data/dashboard_sample_seed.sql` has only 9 Scenario rows (the design package omitted the all-NULL scenarios); production ETL always produces the 12 rows defined by the mapping file.
