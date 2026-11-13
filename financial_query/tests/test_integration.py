"""PostgreSQL integration tests for the Financial Query Service.

Runs only when ``AI_POSTGRES_URL`` is available. Every concept result is
reconciled against a directly-built SQL query over the same bank/date/filters,
satisfying the requirement that the service output matches the database.

The direct SQL here is a test-only reconciliation helper; it reuses the
already-validated identifiers from the Ontology mapping and binds all values as
parameters -- it is not part of the production executor.
"""
import os
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "data_etl" / ".env")
except Exception:
    pass

from sqlalchemy import create_engine, text

from financial_query.models import QueryStatus
from financial_query.service import get_financial_metric
from ontology import get_database_mapping

BANK = -48858
AS_OF = date(2026, 6, 30)
CONCEPTS = ["ALM.NII.BASE", "ALM.NII.U200", "ALM.EVE.BASE", "FIN.ROA", "CAP.TIER1"]


@unittest.skipUnless(os.getenv("AI_POSTGRES_URL"), "AI_POSTGRES_URL is not set")
class QueryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(os.environ["AI_POSTGRES_URL"])

    def _direct_value(self, concept_id):
        mapping = get_database_mapping(concept_id)
        table = mapping["table"]
        column = mapping["column"]
        filters = mapping.get("filters", {}) or {}
        schema, _, tbl = table.partition(".")
        sql = (f'SELECT "{tbl}"."{column}" FROM "{schema}"."{tbl}" '
               f'WHERE "bank_id" = :b AND "as_of_date" = :d')
        params = {"b": BANK, "d": AS_OF}
        for key, val in filters.items():
            sql += f' AND "{key}" = :f_{key}'
            params[f"f_{key}"] = val
        with self.engine.connect() as conn:
            row = conn.execute(text(sql), params).fetchone()
        return row[0] if row else None

    def test_five_concepts_match_direct_sql(self):
        for cid in CONCEPTS:
            with self.subTest(concept=cid):
                result = get_financial_metric(cid, BANK, AS_OF,
                                             engine=self.engine)
                self.assertEqual(result.status, QueryStatus.SUCCESS)
                self.assertEqual(result.value, self._direct_value(cid))

    def test_base_and_u200_not_confused(self):
        base = get_financial_metric("ALM.NII.BASE", BANK, AS_OF,
                                   engine=self.engine)
        u200 = get_financial_metric("ALM.NII.U200", BANK, AS_OF,
                                   engine=self.engine)
        self.assertEqual(base.scenario, "Base")
        self.assertEqual(u200.scenario, "U200")
        self.assertEqual(base.value, self._direct_value("ALM.NII.BASE"))
        self.assertEqual(u200.value, self._direct_value("ALM.NII.U200"))

    def test_different_schemas(self):
        risk_res = get_financial_metric("ALM.NII.BASE", BANK, AS_OF,
                                       engine=self.engine)
        fin_res = get_financial_metric("FIN.ROA", BANK, AS_OF,
                                      engine=self.engine)
        self.assertEqual(risk_res.source["table"].split(".")[0], "risk")
        self.assertEqual(fin_res.source["table"].split(".")[0], "finance")
        self.assertEqual(risk_res.status, QueryStatus.SUCCESS)
        self.assertEqual(fin_res.status, QueryStatus.SUCCESS)

    def test_unknown_bank_not_found(self):
        r = get_financial_metric("ALM.NII.BASE", -999999, AS_OF,
                                engine=self.engine)
        self.assertEqual(r.status, QueryStatus.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
