"""Financial Query Service: map a Concept ID to PostgreSQL and read the metric.

It depends only on the public Ontology Registry API and never hard-codes table
or column names. Adding a new concept is purely a data change in ``banking.ttl``
and ``mappings.yaml`` -- no new query function is required.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional, Union

from ontology import (ConceptNotFoundError, get_concept, get_database_mapping)

from .executor import execute_metric_query
from .models import (DatabaseQueryError, FinancialQueryResult, QueryStatus)


def _normalize_date(as_of_date: Union[date, datetime, str]) -> date:
    if isinstance(as_of_date, datetime):
        return as_of_date.date()
    if isinstance(as_of_date, date):
        return as_of_date
    if isinstance(as_of_date, str):
        return date.fromisoformat(as_of_date)
    raise ValueError("as_of_date must be a date or ISO-8601 string")


def get_financial_metric(concept_id: str, bank_id: int,
                        as_of_date: Union[date, datetime, str],
                        engine: Any = None) -> FinancialQueryResult:
    """Resolve a Concept ID to its PostgreSQL value and return a uniform result."""
    as_of = _normalize_date(as_of_date)

    # 1. The concept must exist in the ontology.
    try:
        concept = get_concept(concept_id)
    except ConceptNotFoundError:
        return FinancialQueryResult(
            status=QueryStatus.INVALID_CONCEPT, concept_id=concept_id,
            bank_id=bank_id, as_of_date=as_of.isoformat(),
            message=f"concept not found: {concept_id}")

    # 2. The concept must have a database mapping.
    try:
        mapping = get_database_mapping(concept_id)
    except (ConceptNotFoundError, KeyError):
        return FinancialQueryResult(
            status=QueryStatus.INVALID_MAPPING, concept_id=concept_id,
            concept_name=concept["pref_label"], bank_id=bank_id,
            as_of_date=as_of.isoformat(),
            message=f"no database mapping for concept: {concept_id}")

    source = {"table": mapping["table"], "column": mapping["column"]}
    scenario = (mapping.get("filters", {}) or {}).get("scenario_code")

    # 3. Read the metric (read-only, parameterised).
    try:
        rows = execute_metric_query(mapping, bank_id, as_of, engine=engine)
    except DatabaseQueryError as exc:
        return FinancialQueryResult(
            status=QueryStatus.DATABASE_ERROR, concept_id=concept_id,
            concept_name=concept["pref_label"], bank_id=bank_id,
            as_of_date=as_of.isoformat(), source=source,
            definition_status=concept["definition_status"], message=str(exc))

    # 4. Classify the outcome.
    if len(rows) == 0:
        status = QueryStatus.NOT_FOUND
        value: Optional[Decimal] = None
        message = "no business record matched the query criteria"
    elif len(rows) > 1:
        status = QueryStatus.AMBIGUOUS_RESULT
        value = None
        message = (f"{len(rows)} rows matched; exactly one expected "
                   "(bank_id + as_of_date + filters must be unique)")
    else:
        # A single row exists; its value may legitimately be NULL.
        value = rows[0]
        status = QueryStatus.SUCCESS
        message = None

    return FinancialQueryResult(
        status=status, concept_id=concept_id,
        concept_name=concept["pref_label"], bank_id=bank_id,
        as_of_date=as_of.isoformat(), value=value, scenario=scenario,
        source=source, definition_status=concept["definition_status"],
        message=message)
