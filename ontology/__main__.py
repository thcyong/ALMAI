"""Minimal CLI for the Financial Ontology module.

Usage (run from the repository root so the ``ontology`` package is importable):

    python -m ontology validate [--check-db] [--db-url URL]
    python -m ontology concept ALM.NII.BASE
    python -m ontology mapping ALM.NII.BASE

Database validation only runs when ``--check-db`` is given; the connection URL
comes from ``--db-url`` or the ``AI_POSTGRES_URL`` environment variable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Read the data_etl .env so `--check-db` finds AI_POSTGRES_URL without manual
# export. This only loads a connection string; it does not import the data_etl
# package, so the ontology stays decoupled.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / "data_etl" / ".env",
                override=False)
except Exception:
    pass

from .registry import ConceptNotFoundError, Ontology
from .validator import validate


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ontology")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate ontology and mappings")
    p_validate.add_argument("--check-db", action="store_true",
                            help="also validate mapped PostgreSQL objects")
    p_validate.add_argument("--db-url", default=os.getenv("AI_POSTGRES_URL"),
                            help="PostgreSQL URL (defaults to AI_POSTGRES_URL)")

    p_concept = sub.add_parser("concept", help="show a concept")
    p_concept.add_argument("concept_id")

    p_mapping = sub.add_parser("mapping", help="show a concept database mapping")
    p_mapping.add_argument("concept_id")
    return parser


def _run_validate(ontology: "Ontology", args) -> dict:
    """Build the validation report, enforcing that --check-db really runs."""
    engine_url = args.db_url if args.check_db else None
    report = validate(ontology.graph, ontology.mappings, engine_url=engine_url)
    # If the user explicitly asked for database validation but it did not run
    # (no --db-url and no AI_POSTGRES_URL), that is a failure, not a pass.
    if args.check_db and not report["database"]["executed"]:
        report["database"].setdefault("errors", []).append(
            "database validation requested (--check-db) but was not executed: "
            "provide --db-url or set AI_POSTGRES_URL")
        report["ok"] = False
    return report


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    ontology = Ontology.load()

    if args.command == "validate":
        report = _run_validate(ontology, args)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if not report["ok"]:
            sys.exit(1)
        return

    if args.command == "concept":
        try:
            data = ontology.get_concept(args.concept_id)
        except ConceptNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    if args.command == "mapping":
        try:
            data = ontology.get_database_mapping(args.concept_id)
        except (ConceptNotFoundError, KeyError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
