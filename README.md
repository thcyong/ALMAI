# ALMAI — Bank Financial Data Platform

ALMAI synchronizes bank financial / risk / analytical indicators from the Dev SQL Server **read-only** into PostgreSQL, and builds a verifiable **Financial Semantic Layer (Ontology)** on top of it, providing a stable, database-decoupled interface for the downstream Financial Query Service.

The two core capabilities are designed as **mutually independent packages that do not import each other**, connected only indirectly through the shared PostgreSQL business database:

| Module | Path | Responsibility | Entry point |
|---|---|---|---|
| Data sync (ETL) | `data_etl/` | Read-only sync from Dev SQL Server into 12 PostgreSQL business tables | `data_etl/debug_run.py` |
| Financial Semantic Layer (Ontology) | `ontology/` | SKOS ontology + concept→PostgreSQL semantic mapping, validation, query API | `python -m ontology` |
| Financial Query Service | `financial_query/` | Generates read-only parameterized SQL by Concept ID via the Ontology mapping, returns a unified result | `python -m financial_query` |

---

## 1. Overall Architecture

```
Dev SQL Server (read-only)
        │  dbo.BankAnalyzingWatches + dbo.DashboardItems
        │  (YAML + 331-field CSV mapping, Decimal cleansing)
        ▼
PostgreSQL business DB  ── 12 tables (core / finance / risk / analysis)
        │               ▲ read-only metadata
        │               │ (table/column/filters validation)
        ▼               │
Financial Ontology  ───┘  (SKOS/Turtle + mappings.yaml)
        │
        ▼
Financial Query Service (financial_query/)  ── calls ontology.get_database_mapping()
        │                                   builds read-only parameterized SQL (SQLAlchemy Core)
        ▼
PostgreSQL business DB  ── read-only query (WHERE bank_id / as_of_date / filters, bound params)
```

- **ETL** is responsible for "pulling data in and keeping it current", only writing business data, without interpreting financial semantics.
- **Ontology** is responsible for "giving data stable, verifiable business names", reading metadata only, never writing data.
- **Financial Query Service** is responsible for "translating names into safe read-only SQL by Concept ID", depending only on the Ontology public API and not maintaining a second copy of the mapping.
- The three are connected through the same PostgreSQL business database but are fully decoupled at the code level.

---

## 2. Module Description

### `data_etl/` — Bank Financial ETL (`banking-dashboard-etl`)

- Read-only Dev SQL Server (`ApplicationIntent=ReadOnly`) → mapped via `configs/dashboard.yaml` + `configs/dashboard_field_mapping.csv` (331 fields) → Decimal cleansing → written to PostgreSQL.
- Lands **12 business tables** across `core / finance / risk / analysis` schemas; the same `BankID + AsOfDate` is replaced entirely within a single transaction (only the latest is kept, no history).
- Design highlights: idempotent table creation, single-transaction rollback, `owner_dataset` isolation, no financial recomputation (NULL/0/negative kept as-is), 235 fields marked "to be verified".
- See [`data_etl/README.md`](data_etl/README.md) for detailed design, run instructions and tests.

### `ontology/` — Financial Semantic Layer (Phase 3)

- Uses standard **SKOS** in `banking.ttl` to define financial domains, subcategories and indicator concepts (currently 11 concepts: 6 upper-level domains + 5 core indicators `ALM.NII.BASE` / `ALM.NII.U200` / `ALM.EVE.BASE` / `FIN.ROA` / `CAP.TIER1`).
- Uses `mappings.yaml` to associate stable **Concept ID** with PostgreSQL `schema.table` / `column` / `filters` (currently 5 valid mappings, e.g. `ALM.NII.BASE → risk.interest_rate_scenario.nii WHERE scenario_code='Base'`).
- Provides `loader` / `registry` / `validator` / `CLI` (`validate` / `concept` / `mapping`).
- Validation has two layers: **offline** (no DB connection, checks ontology and mapping integrity) and **optional database validation** (verifies tables/columns really exist via SQLAlchemy Inspector).
- **Decoupled** from ETL: does not import the `data_etl` package, does not modify any business table, reads metadata only; adding a concept only requires editing data files, not Python code.
- See [`ontology/README.md`](ontology/README.md) for detailed design, API, CLI and tests.

### `financial_query/` — Financial Query Service (Phase 4 MVP)

- Generic query interface `get_financial_metric(concept_id, bank_id, as_of_date)` which, by Concept ID, obtains the mapping via the Ontology Registry and then generates **read-only parameterized SQL** (SQLAlchemy Core) to query PostgreSQL.
- Three-tier responsibility separation: `models.py` (request/result/status/exception), `service.py` (orchestration), `executor.py` (safe read-only SQL execution).
- Security: table/column/filter-column names all come from the validated Ontology mapping and are safely quoted by SQLAlchemy; all values (bank_id, as_of_date, filter values) are bound parameters; the connection runs in a read-only transaction; user-input SQL is never concatenated.
- Unified return status: `success` / `not_found` / `invalid_concept` / `invalid_mapping` / `ambiguous_result` / `database_error`; numeric values are returned as `Decimal` (JSON string), `NULL` and `0` are strictly distinguished, and no unit conversion or financial computation is performed.
- No specific indicator (NII/EVE/ROA/Tier1) table name is hard-coded; adding a concept only requires updating `banking.ttl` + `mappings.yaml` to be queryable through the same interface.

---

## 3. Design Principles

1. **Decoupling**: ETL, Ontology, and Financial Query Service are three independent packages; the query service obtains mappings only through the `ontology` public API, does not directly couple to ETL, and does not duplicate a second copy of the mapping inside `financial_query`.
2. **Data-driven**: adding a financial field only updates `dashboard_field_mapping.csv`; adding a concept only updates `banking.ttl` + `mappings.yaml`; the main flow code stays stable.
3. **Read-only and idempotent**: ETL reads the source read-only, creates tables idempotently, replaces in a single transaction; Ontology reads database metadata, Financial Query Service reads business data — none of the three ever writes business data.
4. **Stable identifiers**: each financial concept has a fixed Concept ID and URI (`https://almai.example/ontology/concept/<ID>`) that does not change when underlying table/column names change.
5. **Safe queries**: semantic mapping only declares `table` / `column` / `filters` and explicitly forbids SQL expressions; the query service builds **parameterized read-only SQL** with SQLAlchemy Core accordingly, never concatenating user input.
6. **Explicit to-be-confirmed**: caliber rules whose amount unit, forecast period, or computation rule are unclear (e.g. `ALM.NII.U200`, `FIN.ROA`) are marked `needs_review` in the ontology and never assumed.

---

## 4. Current Progress

| Phase | Content | Status |
|---|---|---|
| Phase 1–2 | Data sync ETL: 331-field mapping, 12 business tables, single-transaction write, `debug_run.py`, unit tests | ✅ Done |
| Phase 3 | Financial ontology + semantic mapping + Registry + Validator (strict identifier validation / duplicate-key detection / cycle detection) + CLI + 18 tests (incl. real PostgreSQL validation) | ✅ Done |
| Phase 4 | Financial Query Service MVP: read-only parameterized SQL by Concept ID, unified result model, 11 tests (incl. 5-concept PG reconciliation) | ✅ Done |

---

## 5. Quick Start

### 5.1 Data Sync (ETL)

```bash
cd data_etl
# Configure DEV_SQLSERVER_* and AI_POSTGRES_URL in .env
python debug_run.py        # Sync fixed test bank/date (TEST_BANK_ID=-48858, TEST_AS_OF=2026-06-30)
```

Tests:

```bash
cd data_etl
python -m unittest discover -s tests -v   # PG cases run only when AI_ETL_TEST_POSTGRES_URL is set
```

### 5.2 Financial Semantic Layer (Ontology)

```bash
cd d:/python/ALMAI          # repo root (so the ontology package is importable)
python -m ontology validate            # offline validation of ontology + mapping
python -m ontology validate --check-db # validate tables/columns against real PostgreSQL
python -m ontology concept ALM.NII.BASE
python -m ontology mapping ALM.NII.BASE
```

Tests:

```bash
cd d:/python/ALMAI
python -m unittest discover -s ontology/tests -v   # or python -m pytest ontology/tests -v
# The database validation cases run only when AI_POSTGRES_URL is set
```

Debugging: the repo provides `.vscode/launch.json`; in VS Code / CodeBuddy press **F5** and select an `ontology:*` configuration to debug with breakpoints.

### 5.3 Financial Query Service (financial_query)

```bash
cd d:/python/ALMAI
python -m financial_query --concept ALM.NII.BASE --bank-id -48858 --as-of-date 2026-06-30
# Output unified JSON: status / value (Decimal string) / scenario / source / definition_status
```

Tests (incl. real PostgreSQL reconciliation):

```bash
python -m unittest discover -s financial_query/tests -v
# or python -m pytest financial_query/tests -v
# Integration cases run only when AI_POSTGRES_URL is set (reconciled against direct SQL)
```

---

## 6. Dependencies

- **data_etl**: `SQLAlchemy>=2.0` `pyodbc>=5.1` `psycopg[binary]>=3.1` `PyYAML>=6` `python-dotenv>=1`, Python `>=3.11` (see `data_etl/pyproject.toml`).
- **ontology**: `rdflib` `PyYAML>=6` `python-dotenv>=1`; identifier/mapping validation and connection config reuse `data_etl`'s `_DatasetLoader` and `SQLAlchemy` (no duplicate implementation).
- **financial_query**: `SQLAlchemy` (read-only query, reuses `AI_POSTGRES_URL`), `python-dotenv`; no new database configuration system is introduced.
- Development currently uses the `AI2` conda environment.

---

## 7. Related Documents

- [Data sync module](data_etl/README.md)
- [Financial semantic layer](ontology/README.md)
- Financial Query Service source: `financial_query/` (`models.py` / `service.py` / `executor.py` / `__main__.py`)

---

## 8. Chat Demo (LLM Try-out)

`chat/` is an optional, additive demo layer (it does **not** modify `data_etl` / `ontology` / `financial_query`):

- `chat/llm.py` wraps the Volcengine Ark (OpenAI-compatible) endpoint and uses **function calling** to translate natural language into `get_financial_metric(concept_id, bank_id, as_of_date)` parameters. The LLM only produces query parameters; the actual PostgreSQL read is always performed by `financial_query` (parameterized, read-only).
- `chat/app.py` is a FastAPI backend (`GET /` serves the UI, `POST /api/chat` proxies to the LLM + query service).
- `chat/static/index.html` is a minimal chat UI.
- Credentials live in `chat/.env` (git-ignored); the LLM API key is never sent to the browser.

Run:

```bash
cd d:/python/ALMAI
$env:PYTHONPATH="d:/python/ALMAI"
uvicorn chat.app:app --reload --port 8000
# open http://localhost:8000
```
