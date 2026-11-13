"""Minimal CLI for the Financial Query Service.

Usage (run from the repository root so both ``ontology`` and ``financial_query``
are importable):

    python -m financial_query --concept ALM.NII.BASE --bank-id -48858 --as-of-date 2026-06-30

Outputs a single JSON object with the uniform query result. Exit code is
non-zero only on a database error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / "data_etl" / ".env",
                override=False)
except Exception:
    pass

from .executor import get_engine
from .models import QueryStatus
from .service import get_financial_metric


def _result_to_json(result: "object") -> dict:
    value = result.value
    return {
        "status": result.status.value,
        "concept_id": result.concept_id,
        "concept_name": result.concept_name,
        "bank_id": result.bank_id,
        "as_of_date": result.as_of_date,
        "value": str(value) if isinstance(value, Decimal) else value,
        "scenario": result.scenario,
        "source": result.source,
        "definition_status": result.definition_status,
        "message": result.message,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="financial_query")
    parser.add_argument("--concept", required=True, help="Ontology Concept ID")
    parser.add_argument("--bank-id", required=True, type=int)
    parser.add_argument("--as-of-date", required=True,
                        help="ISO date, e.g. 2026-06-30")
    parser.add_argument("--db-url", default=os.getenv("AI_POSTGRES_URL"),
                        help="PostgreSQL URL (defaults to AI_POSTGRES_URL)")
    args = parser.parse_args(argv)

    engine = get_engine(args.db_url) if args.db_url else None
    result = get_financial_metric(args.concept, args.bank_id,
                                 args.as_of_date, engine=engine)
    print(json.dumps(_result_to_json(result), indent=2, ensure_ascii=False))
    if result.status == QueryStatus.DATABASE_ERROR:
        sys.exit(1)


if __name__ == "__main__":
    main()
