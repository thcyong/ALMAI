"""Input/output models and status/error definitions for the Financial Query Service.

These are plain dataclasses -- no new ORM models and no new database tables. They
describe a single-concept query request/result and the finite set of outcomes a
query can produce.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional


class QueryStatus(str, Enum):
    """Finite set of outcomes returned by the query service."""
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    INVALID_CONCEPT = "invalid_concept"
    INVALID_MAPPING = "invalid_mapping"
    AMBIGUOUS_RESULT = "ambiguous_result"
    DATABASE_ERROR = "database_error"


class DatabaseQueryError(RuntimeError):
    """Raised when the PostgreSQL read fails.

    The message is sanitised so credentials / connection strings are never
    leaked to callers.
    """


# A small allow-list of characters that should never survive sanitisation in a
# connection string embedded in an error.
_CRED_RE = re.compile(r"(://[^:/\s]+:)[^@\s]+@")


def sanitize_error(message: str) -> str:
    """Strip obvious credentials from a database error message."""
    return _CRED_RE.sub(r"\1***@", message)


@dataclass
class FinancialQueryRequest:
    concept_id: str
    bank_id: int
    as_of_date: "date | str"  # date or ISO-8601 string; normalised by the service


@dataclass
class FinancialQueryResult:
    status: QueryStatus
    concept_id: str
    concept_name: Optional[str] = None
    bank_id: Optional[int] = None
    as_of_date: Optional[str] = None  # ISO string in the result
    value: Optional[Decimal] = None
    scenario: Optional[str] = None
    source: Optional[dict[str, str]] = None
    definition_status: Optional[str] = None
    message: Optional[str] = None
