"""Extract -> Transform -> Save for one bank/date and paged backfill."""
from __future__ import annotations

from datetime import date

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from bank_etl.config import DatasetSpec
from bank_etl.postgres import init_database, replace_business_scope
from bank_etl.sqlserver import MultipleSourceRecordsError, read_source_rows
from bank_etl.transform import transform_dataset


def _base_nii_eve(grouped: dict) -> dict[str, str | None]:
    for row in grouped.get("risk.interest_rate_scenario", []):
        if row.get("scenario_code") == "Base":
            return {
                name: None if row.get(name) is None else str(row[name])
                for name in ("nii", "eve")
            }
    return {}


def sync_one(source_engine: Engine, ai_engine: Engine, spec: DatasetSpec,
             bank_id: int, as_of: date) -> dict[str, object]:
    """Read and validate Dev first; PostgreSQL is touched only afterwards.

    Tables are created automatically when missing, so a bare sync works even
    on a fresh database. A missing source row reports ``not_found`` and leaves
    existing data intact.
    """
    init_database(ai_engine)
    rows = read_source_rows(source_engine, spec, bank_id, as_of)
    if len(rows) > 1:
        raise MultipleSourceRecordsError(
            f"{len(rows)} source rows for bank {bank_id} on {as_of}; "
            "the configured business key must identify exactly one summary row")
    base = {
        "dataset": spec.dataset_code,
        "bank_id": bank_id,
        "as_of_date": as_of.isoformat(),
        "source_fields": len(spec.mapping.rules),
    }
    if not rows:
        return {**base, "status": "not_found", "tables": {},
                "base_nii_eve": {}, "preserved_existing_data": True}

    grouped = transform_dataset(rows[0], spec.mapping, bank_id, as_of)
    with Session(ai_engine) as session, session.begin():
        written = replace_business_scope(session, spec, bank_id, as_of, grouped)
    return {**base, "status": "success", "tables": written,
            "base_nii_eve": _base_nii_eve(grouped),
            "preserved_existing_data": False}
