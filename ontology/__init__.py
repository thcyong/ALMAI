"""ALMAI lightweight Financial Ontology (Phase 3).

A small, dependency-light SKOS ontology plus a semantic mapping layer that
links stable financial Concept IDs to PostgreSQL targets. It is fully decoupled
from the existing ETL: it never writes business data and never imports the
``data_etl`` package.

Public API
----------
* ``get_concept(concept_id)``           -> structured concept data
* ``get_concept_label(concept_id)``     -> English prefLabel
* ``get_broader_concepts(concept_id)``  -> broader concept ids
* ``get_related_concepts(concept_id)``  -> related concept ids
* ``get_database_mapping(concept_id)``  -> {table, column, filters}
* ``list_concepts(domain=None)``        -> sorted concept ids
* ``validate_ontology()``               -> offline validation report

Extending the ontology with a new concept only requires editing
``banking.ttl`` and ``mappings.yaml`` -- no change to this module is needed.
"""
from __future__ import annotations

from .loader import ALMC, ONTO, SKOS, load_mappings, load_ontology
from .registry import ConceptNotFoundError, Ontology
from .validator import validate, validate_database, validate_offline

_default: Ontology | None = None


def _ontology() -> Ontology:
    global _default
    if _default is None:
        _default = Ontology.load()
    return _default


def get_concept(concept_id: str) -> dict:
    return _ontology().get_concept(concept_id)


def get_concept_label(concept_id: str) -> str:
    return _ontology().get_concept_label(concept_id)


def get_broader_concepts(concept_id: str) -> list[str]:
    return _ontology().get_broader_concepts(concept_id)


def get_related_concepts(concept_id: str) -> list[str]:
    return _ontology().get_related_concepts(concept_id)


def get_database_mapping(concept_id: str) -> dict:
    return _ontology().get_database_mapping(concept_id)


def list_concepts(domain: str | None = None) -> list[str]:
    return _ontology().list_concepts(domain)


def validate_ontology() -> dict:
    onto = _ontology()
    return validate(onto.graph, onto.mappings)


__all__ = [
    "ALMC", "ONTO", "SKOS",
    "ConceptNotFoundError", "Ontology",
    "load_ontology", "load_mappings",
    "validate", "validate_offline", "validate_database",
    "get_concept", "get_concept_label", "get_broader_concepts",
    "get_related_concepts", "get_database_mapping", "list_concepts",
    "validate_ontology",
]
