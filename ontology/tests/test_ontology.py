"""Tests for the lightweight Financial Ontology module.

    # from the repository root (d:/python/ALMAI)
    python -m unittest discover -s ontology/tests -v

PostgreSQL checks run only when AI_POSTGRES_URL points at a disposable
database; otherwise they are skipped.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load the data_etl .env so the PostgreSQL validation tests can find
# AI_POSTGRES_URL. This only reads a connection string; it does not import the
# data_etl package, so the ontology stays decoupled.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "data_etl" / ".env")
except Exception:
    pass

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF

import argparse

from ontology.loader import ALMC, ONTO, SKOS, load_mappings
from ontology.registry import ConceptNotFoundError, Ontology
from ontology.validator import validate, validate_database, validate_offline
from ontology.__main__ import _run_validate

CORE = ["ALM.NII.BASE", "ALM.NII.U200", "ALM.EVE.BASE", "FIN.ROA", "CAP.TIER1"]


class OntologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.onto = Ontology.load()
        cls.graph = cls.onto.graph
        cls.mappings = cls.onto.mappings

    # 1. Ontology TTL loads correctly
    def test_ontology_ttl_loads(self):
        self.assertGreaterEqual(len(self.onto.concept_ids), 11)

    # 2. The five Phase 3 core concepts exist
    def test_five_core_concepts_exist(self):
        for cid in CORE:
            self.assertIn(cid, self.onto.concept_ids)

    # 3. Financial domain hierarchy is correct
    def test_domain_hierarchy(self):
        self.assertEqual(self.onto.get_broader_concepts("Banking"), [])
        self.assertEqual(self.onto.get_broader_concepts("Finance"), ["Banking"])
        self.assertEqual(self.onto.get_broader_concepts("Earnings"), ["Finance"])
        self.assertEqual(self.onto.get_broader_concepts("Capital"), ["Finance"])
        self.assertEqual(self.onto.get_broader_concepts("Risk"), ["Banking"])
        self.assertEqual(self.onto.get_broader_concepts("InterestRateRisk"), ["Risk"])
        self.assertEqual(self.onto.get_broader_concepts("ALM.NII.BASE"),
                         ["InterestRateRisk"])
        self.assertEqual(self.onto.get_broader_concepts("FIN.ROA"), ["Earnings"])
        self.assertEqual(self.onto.get_broader_concepts("CAP.TIER1"), ["Capital"])

    # 4. Concept labels are correct
    def test_concept_labels(self):
        self.assertEqual(self.onto.get_concept_label("ALM.NII.BASE"),
                         "Base Forecast NII")
        self.assertEqual(self.onto.get_concept_label("ALM.NII.U200"),
                         "U200 Forecast NII")
        self.assertEqual(self.onto.get_concept_label("ALM.EVE.BASE"),
                         "Base Economic Value of Equity")
        self.assertEqual(self.onto.get_concept_label("FIN.ROA"),
                         "Return on Assets")
        self.assertEqual(self.onto.get_concept_label("CAP.TIER1"),
                         "Tier 1 Capital")

    # 5. Concept mapping shape is correct
    def test_concept_mapping_shape(self):
        self.assertEqual(
            self.onto.get_database_mapping("ALM.NII.BASE"),
            {"concept_id": "ALM.NII.BASE",
             "table": "risk.interest_rate_scenario",
             "column": "nii",
             "filters": {"scenario_code": "Base"}})

    # 6. Base NII maps to the Base scenario
    def test_base_nii_maps_to_base_scenario(self):
        self.assertEqual(
            self.onto.get_database_mapping("ALM.NII.BASE")["filters"],
            {"scenario_code": "Base"})

    # 7. U200 NII maps to the U200 scenario
    def test_u200_nii_maps_to_u200_scenario(self):
        self.assertEqual(
            self.onto.get_database_mapping("ALM.NII.U200")["filters"],
            {"scenario_code": "U200"})

    # 8. NII and EVE are not cross-mapped
    def test_nii_and_eve_not_cross_mapped(self):
        self.assertEqual(self.onto.get_database_mapping("ALM.NII.BASE")["column"],
                         "nii")
        self.assertEqual(self.onto.get_database_mapping("ALM.EVE.BASE")["column"],
                         "eve")
        self.assertNotEqual(
            self.onto.get_database_mapping("ALM.NII.BASE")["column"], "eve")

    # 9. An unknown concept raises a clear error
    def test_unknown_concept_raises(self):
        with self.assertRaises(ConceptNotFoundError):
            self.onto.get_concept("DOES.NOT.EXIST")
        with self.assertRaises(ConceptNotFoundError):
            self.onto.get_database_mapping("DOES.NOT.EXIST")

    # 11. An invalid mapping configuration is rejected
    def test_invalid_mapping_rejected(self):
        bad = {
            "source_dataset": "dashboard",
            "concepts": {
                # missing column
                "ALM.NII.BASE": {"table": "risk.interest_rate_scenario"},
                # filters not a mapping
                "ALM.EVE.BASE": {"table": "risk.interest_rate_scenario",
                                 "column": "eve", "filters": ["Base"]},
                # table name has no schema
                "FIN.ROA": {"table": "earnings", "column": "roa"},
            },
        }
        report = validate_offline(self.graph, bad)
        self.assertTrue(report["mappings"]["errors"])
        self.assertFalse(report["mappings"]["errors"] == [])

    # 12. Ontology validation does not require a running PostgreSQL
    def test_validate_offline_no_db(self):
        report = validate(self.graph, self.mappings)  # no engine_url
        self.assertFalse(report["database"]["executed"])
        self.assertTrue(report["ok"])
        self.assertFalse(report["ontology"]["errors"])
        self.assertFalse(report["mappings"]["errors"])

    # 14. Adding a concept needs no registry code change
    def test_new_concept_needs_no_registry_change(self):
        g = Graph()
        g.add((ALMC["EXTRA.X"], RDF.type, SKOS["Concept"]))
        g.add((ALMC["EXTRA.X"], SKOS["prefLabel"], Literal("Extra Metric", lang="en")))
        g.add((ALMC["EXTRA.X"], SKOS["broader"], ALMC["Finance"]))
        g.add((ALMC["EXTRA.X"], ONTO["domain"], Literal("Finance")))
        g.add((ALMC["EXTRA.X"], ONTO["definitionStatus"], Literal("confirmed")))
        maps = {"source_dataset": "dashboard",
                "concepts": {"EXTRA.X": {"table": "finance.earnings",
                                         "column": "roa"}}}
        extra = Ontology(g, maps)
        self.assertIn("EXTRA.X", extra.list_concepts())
        self.assertEqual(extra.get_concept_label("EXTRA.X"), "Extra Metric")
        self.assertEqual(extra.get_database_mapping("EXTRA.X")["column"], "roa")


@unittest.skipUnless(os.getenv("AI_POSTGRES_URL"),
                     "AI_POSTGRES_URL is not set")
class PostgresValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.onto = Ontology.load()
        cls.graph = cls.onto.graph
        cls.mappings = cls.onto.mappings
        cls.url = os.environ["AI_POSTGRES_URL"]

    # 10. Unknown tables / columns are detected against the real catalog
    def test_unknown_table_column_detected(self):
        bad = {
            "source_dataset": "dashboard",
            "concepts": {
                "ALM.NII.BASE": {"table": "risk.no_such_table", "column": "nii"},
                "ALM.EVE.BASE": {"table": "risk.interest_rate_scenario",
                                 "column": "no_such_column"},
            },
        }
        report = validate_database(self.graph, bad, self.url)
        self.assertTrue(report["executed"])
        self.assertTrue(any("does not exist" in e for e in report["errors"]))

    # 13. Database validation runs independently when connected
    def test_database_validation_runs_when_connected(self):
        report = validate(self.graph, self.mappings, engine_url=self.url)
        self.assertTrue(report["database"]["executed"])
        self.assertFalse(report["database"]["errors"])


class OntologyFixesTests(unittest.TestCase):
    """Regression tests for the Phase 4 ontology hardening fixes."""

    @classmethod
    def setUpClass(cls):
        cls.onto = Ontology.load()
        cls.graph = cls.onto.graph

    # 1.1 Strict PostgreSQL identifier validation
    def test_strict_identifier_rejection(self):
        bad = {
            "source_dataset": "dashboard",
            "concepts": {
                "ALM.NII.BASE": {"table": "risk.interest_rate_scenario",
                                 "column": "nii || eve"},
                "FIN.ROA": {"table": "finance; DROP", "column": "roa"},
                "CAP.TIER1": {"table": "finance.capital", "column": "tier1",
                              "filters": {"scenario_code OR 1=1": "Base"}},
            },
        }
        report = validate_offline(self.graph, bad)
        errors = " ".join(report["mappings"]["errors"])
        self.assertTrue(report["mappings"]["errors"])
        self.assertIn("nii || eve", errors)             # column SQL fragment
        self.assertIn("finance; DROP", errors)           # table SQL fragment
        self.assertIn("scenario_code OR 1=1", errors)    # filter column SQL

    # 1.2 --check-db without a connection must fail, not pass
    def test_check_db_without_connection_fails(self):
        args = argparse.Namespace(command="validate", check_db=True, db_url=None)
        report = _run_validate(self.onto, args)
        self.assertFalse(report["ok"])
        self.assertTrue(any("not executed" in e
                            for e in report["database"]["errors"]))

    # 1.3 Duplicate Concept ID in mappings must raise
    def test_duplicate_concept_id_rejected(self):
        import os
        import tempfile
        content = (
            "source_dataset: dashboard\n"
            "concepts:\n"
            "  ALM.NII.BASE:\n"
            "    table: risk.interest_rate_scenario\n"
            "    column: nii\n"
            "  ALM.NII.BASE:\n"
            "    table: finance.earnings\n"
            "    column: roa\n"
        )
        handle = tempfile.NamedTemporaryFile("w", suffix=".yaml",
                                            delete=False, encoding="utf-8")
        try:
            handle.write(content)
            handle.close()
            with self.assertRaises(ValueError):
                load_mappings(handle.name)
        finally:
            os.unlink(handle.name)

    # 1.4 Cycle detection must follow multiple broader parents
    def test_cycle_detection_multiple_parents(self):
        g = Graph()
        for x in ("A", "B", "C"):
            g.add((ALMC[x], RDF.type, SKOS["Concept"]))
            g.add((ALMC[x], SKOS["prefLabel"], Literal(x, lang="en")))
            g.add((ALMC[x], ONTO["domain"], Literal("Test")))
            g.add((ALMC[x], ONTO["definitionStatus"], Literal("confirmed")))
        # A broader B, A broader C, C broader A  -> cycle via C
        g.add((ALMC["A"], SKOS["broader"], ALMC["B"]))
        g.add((ALMC["A"], SKOS["broader"], ALMC["C"]))
        g.add((ALMC["C"], SKOS["broader"], ALMC["A"]))
        report = validate_offline(g, {"source_dataset": "dashboard", "concepts": {}})
        self.assertTrue(any("circular" in e
                            for e in report["ontology"]["errors"]))


if __name__ == "__main__":
    unittest.main()
