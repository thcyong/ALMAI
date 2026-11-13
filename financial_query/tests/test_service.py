"""Offline unit tests for the Financial Query Service.

The PostgreSQL executor is mocked, so these run without any database. They cover
every status branch: success, success+NULL, not_found, ambiguous, invalid_concept,
invalid_mapping and database_error.
"""
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from financial_query.models import DatabaseQueryError, QueryStatus
from financial_query.service import get_financial_metric

CONCEPT = "ALM.NII.BASE"
BANK = -48858
AS_OF = date(2026, 6, 30)


class ServiceOfflineTests(unittest.TestCase):
    def _with_rows(self, rows):
        with patch("financial_query.service.execute_metric_query",
                   return_value=rows) as mock_exec:
            result = get_financial_metric(CONCEPT, BANK, AS_OF)
            self.assertTrue(mock_exec.called)
            return result

    def test_success(self):
        r = self._with_rows([Decimal("1391523.63690477")])
        self.assertEqual(r.status, QueryStatus.SUCCESS)
        self.assertEqual(r.value, Decimal("1391523.63690477"))
        self.assertEqual(r.scenario, "Base")
        self.assertEqual(r.source,
                         {"table": "risk.interest_rate_scenario", "column": "nii"})
        self.assertEqual(r.definition_status, "confirmed")

    def test_success_null_value(self):
        # A matching row exists but the metric value is NULL.
        r = self._with_rows([None])
        self.assertEqual(r.status, QueryStatus.SUCCESS)
        self.assertIsNone(r.value)

    def test_not_found(self):
        # No matching business record at all.
        r = self._with_rows([])
        self.assertEqual(r.status, QueryStatus.NOT_FOUND)
        self.assertIsNone(r.value)

    def test_ambiguous_result(self):
        # More than one row -> violates the expected single-row uniqueness.
        r = self._with_rows([Decimal("1"), Decimal("2")])
        self.assertEqual(r.status, QueryStatus.AMBIGUOUS_RESULT)
        self.assertIsNone(r.value)

    def test_invalid_concept(self):
        r = get_financial_metric("NOPE.CONCEPT", BANK, AS_OF)
        self.assertEqual(r.status, QueryStatus.INVALID_CONCEPT)

    def test_invalid_mapping(self):
        # "Banking" is an ontology concept but has no database mapping.
        r = get_financial_metric("Banking", BANK, AS_OF)
        self.assertEqual(r.status, QueryStatus.INVALID_MAPPING)

    def test_database_error(self):
        with patch("financial_query.service.execute_metric_query",
                   side_effect=DatabaseQueryError("connection refused")):
            r = get_financial_metric(CONCEPT, BANK, AS_OF)
        self.assertEqual(r.status, QueryStatus.DATABASE_ERROR)
        self.assertIn("connection refused", r.message or "")


if __name__ == "__main__":
    unittest.main()
