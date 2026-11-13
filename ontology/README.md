# ALMAI Lightweight Financial Ontology (Phase 3)

A lightweight, extensible, and verifiable **Financial Ontology** module that builds a reliable semantic association between financial concepts and the PostgreSQL business tables already established by `data_etl`, providing the foundation for the next-stage **Financial Query Service**.

This module is fully decoupled from the existing ETL:

- It does not modify any Dev SQL Server structure, Dashboard mapping, PostgreSQL business table, or bank data.
- It accesses database **metadata** (whether tables/columns exist) read-only, and never writes business data.
- It does not import the `data_etl` package; adding financial concepts only requires editing data files, not Python code.

## 1. Three-Layer Structure

| Layer | File | Responsibility |
|---|---|---|
| Layer 1 — Financial Ontology | `banking.ttl` | Defines financial domains, subcategories, indicator concepts and their `skos:broader` / `skos:related` relations |
| Layer 2 — Semantic Mapping | `mappings.yaml` | Concept → PostgreSQL `schema.table` / `column` / `filters` |
| Layer 3 — Financial Data | (existing PostgreSQL) | 12 business tables, not modified by this module |

## 2. Concept ID and URI Rules

Concepts use stable business IDs, e.g. `ALM.NII.BASE`, `FIN.ROA`, `CAP.TIER1`. Each ID maps to a fixed URI: `https://almai.example/ontology/concept/<ConceptID>`. The URI does not change when database table names change, so renaming a field only requires updating `mappings.yaml`, with no change to the ontology or code.

Current concepts (11):

- Upper-level domains: `Banking` → `Finance` (`Earnings`, `Capital`), `Risk` (`InterestRateRisk`)
- Core indicators: `ALM.NII.BASE`, `ALM.NII.U200`, `ALM.EVE.BASE`, `FIN.ROA`, `CAP.TIER1`

## 3. SKOS Vocabulary

`banking.ttl` uses standard SKOS properties:

- `skos:Concept` / `skos:prefLabel` / `skos:altLabel` / `skos:definition`
- `skos:broader` / `skos:narrower` / `skos:related`

Note: `skos:broader` expresses a **classification hierarchy**, not OWL class inheritance. The custom properties `onto:domain` (business domain) and `onto:definitionStatus` (`confirmed` / `needs_review`) mark the business domain and the financial-caliber confirmation status.

## 4. Module API

```python
import ontology

ontology.list_concepts()                       # all concept IDs
ontology.list_concepts(domain="Interest Rate Risk")
ontology.get_concept("ALM.NII.BASE")           # structured concept data
ontology.get_concept_label("ALM.NII.BASE")     # "Base Forecast NII"
ontology.get_broader_concepts("ALM.NII.BASE")  # ["InterestRateRisk"]
ontology.get_related_concepts("ALM.NII.BASE")  # ["ALM.EVE.BASE", "ALM.NII.U200"]
ontology.get_database_mapping("ALM.NII.BASE")
# {"concept_id": "ALM.NII.BASE", "table": "risk.interest_rate_scenario",
#  "column": "nii", "filters": {"scenario_code": "Base"}}
ontology.validate_ontology()                   # offline validation report
```

The next-stage Query Service calls `get_database_mapping()` directly to obtain `table/column/filters` and build parameterized SQL (SQL generation is not implemented in this phase).

## 5. CLI

Run from the repo root (so the `ontology` package is importable):

```bash
# Validate ontology and mapping (offline)
python -m ontology validate

# Validate ontology + real PostgreSQL catalog
python -m ontology validate --check-db
python -m ontology validate --check-db --db-url postgresql+psycopg://user:pass@host/db

# Inspect a concept
python -m ontology concept ALM.NII.BASE

# Inspect a mapping
python -m ontology mapping ALM.NII.BASE
```

The `--check-db` connection string comes from `--db-url`, otherwise from the `AI_POSTGRES_URL` environment variable. When `--check-db` is explicitly given but no usable connection is available (no `--db-url` and no `AI_POSTGRES_URL`), validation **fails with a non-zero exit code** and does not silently report "not executed" as passed; only the pure offline mode without `--check-db` marks database validation as *skipped*.

## 6. Validation (Offline + Database)

`ontology.validator.validate(graph, mappings, engine_url=None)` returns:

```json
{
  "ok": true,
  "ontology": {"errors": [], "warnings": []},
  "mappings": {"errors": [], "warnings": []},
  "database": {"executed": false, "errors": [], "warnings": ["...skipped..."]}
}
```

- **Offline**: RDF syntax, Concept ID stability and uniqueness, English `prefLabel`, `broader` validity, classification cycles (DFS, supports a concept with multiple parents), `onto:domain`, definition status; mapping `schema.table` and `column` / `filter` column names must pass a strict identifier regex (rejecting SQL fragments such as `nii || eve` or `scenario_code OR 1=1` — users cannot control SQL table/column names); duplicate Concept IDs are rejected directly by the strict YAML Loader (reusing `data_etl`'s `_DatasetLoader`); Base/U200 distinction, NII caliber distinction, ambiguous mapping detection.
- **Database** (optional): via SQLAlchemy Inspector, verifies that the `schema` / `table` / `column` / `filter` columns really exist and that the indicator column type is suitable for financial numerics.

## 7. Tests

```bash
cd d:/python/ALMAI
python -m unittest discover -s ontology/tests -v
# or: python -m pytest ontology/tests -v
```

PostgreSQL cases run only when `AI_POSTGRES_URL` is available, otherwise they are skipped.

## 8. Financial Caliber To-Be-Confirmed List

- `ALM.NII.U200`: the U200 scenario interest-rate shock rule is not formally defined; marked `needs_review`, do not assume.
- `FIN.ROA`: the calculation period (annualized/periodic) and denominator caliber (average assets vs. period-end assets) are unconfirmed; marked `needs_review`.
- `ALM.NII.BASE`: explicitly a **forecast** NII, not equivalent to realized/book financial NII.
- `CAP.TIER1`: a capital **amount**, explicitly distinct from the Tier 1 Capital Ratio.
- The calibers of 235 Dashboard fields still follow `data_etl`'s "to be verified" mark; this phase only connects the 5 core concepts.

## 9. Extension

To add a financial concept (e.g. `ALM.NII.D100`):

1. Add `almc:ALM.NII.D100 a skos:Concept ; ...` in `banking.ttl`.
2. Add the corresponding `table/column/filters` in `mappings.yaml`.

No changes to `loader.py` / `registry.py` / `validator.py` are needed.

### Used by the Financial Query Service

The `financial_query` module directly reuses this Ontology's Registry and does not maintain a second copy of the mapping:

```python
from financial_query import get_financial_metric

result = get_financial_metric("ALM.NII.BASE", bank_id=-48858, as_of_date="2026-06-30")
# result.status == "success", result.value is Decimal, result.source == {"table", "column"}
```
