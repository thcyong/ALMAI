"""Unified, read-only API over the Financial Ontology and its mappings.

Extending the ontology with a new concept requires only a new entry in
``banking.ttl`` and ``mappings.yaml`` -- none of the code below needs to change.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rdflib import Graph, URIRef

from .loader import (ALMC, DEFAULT_MAPPINGS, DEFAULT_ONTOLOGY, ONTO, RDF, SKOS,
                     load_mappings, load_ontology)


class ConceptNotFoundError(KeyError):
    """Raised when a Concept ID is not declared in the ontology."""


class Ontology:
    """In-memory view of the ontology graph plus the semantic mappings."""

    def __init__(self, graph: Graph, mappings: dict[str, Any]) -> None:
        self.graph = graph
        self.mappings = mappings
        self._concept_ids = self._discover_concept_ids(graph)

    @staticmethod
    def _discover_concept_ids(graph: Graph) -> set[str]:
        ids: set[str] = set()
        for subject in graph.subjects(RDF["type"], SKOS["Concept"]):
            ids.add(str(subject).replace(str(ALMC), ""))
        return ids

    @classmethod
    def load(cls, ontology_path: Path | str = DEFAULT_ONTOLOGY,
             mappings_path: Path | str = DEFAULT_MAPPINGS) -> "Ontology":
        return cls(load_ontology(ontology_path), load_mappings(mappings_path))

    # -- concept ids -------------------------------------------------------

    @property
    def concept_ids(self) -> set[str]:
        return set(self._concept_ids)

    def _uri(self, concept_id: str) -> URIRef:
        if concept_id not in self._concept_ids:
            raise ConceptNotFoundError(f"concept not found: {concept_id}")
        return ALMC[concept_id]

    @staticmethod
    def _local(uri: URIRef) -> str:
        return str(uri).replace(str(ALMC), "")

    # -- concept read API --------------------------------------------------

    def get_concept(self, concept_id: str) -> dict[str, Any]:
        uri = self._uri(concept_id)
        graph = self.graph
        pref = list(graph.objects(uri, SKOS["prefLabel"]))
        alts = [str(o) for o in graph.objects(uri, SKOS["altLabel"])]
        defs = list(graph.objects(uri, SKOS["definition"]))
        broaders = [self._local(s) for s in graph.objects(uri, SKOS["broader"])]
        narrowers = [self._local(s)
                     for s in graph.subjects(SKOS["broader"], uri)]
        related = [self._local(s) for s in graph.objects(uri, SKOS["related"])]
        domains = [str(o) for o in graph.objects(uri, ONTO["domain"])]
        statuses = [str(o) for o in graph.objects(uri, ONTO["definitionStatus"])]
        return {
            "concept_id": concept_id,
            "uri": str(uri),
            "pref_label": str(pref[0]) if pref else None,
            "alt_labels": alts,
            "definition": str(defs[0]) if defs else None,
            "broader": broaders,
            "narrower": narrowers,
            "related": related,
            "domain": domains[0] if domains else None,
            "definition_status": statuses[0] if statuses else None,
        }

    def get_concept_label(self, concept_id: str) -> str:
        label = self.get_concept(concept_id)["pref_label"]
        if label is None:
            raise ConceptNotFoundError(f"concept {concept_id} has no prefLabel")
        return label

    def get_broader_concepts(self, concept_id: str) -> list[str]:
        return self.get_concept(concept_id)["broader"]

    def get_related_concepts(self, concept_id: str) -> list[str]:
        return self.get_concept(concept_id)["related"]

    def list_concepts(self, domain: str | None = None) -> list[str]:
        if domain is None:
            return sorted(self._concept_ids)
        return sorted(cid for cid in self._concept_ids
                      if self.get_concept(cid)["domain"] == domain)

    # -- mapping read API --------------------------------------------------

    def get_database_mapping(self, concept_id: str) -> dict[str, Any]:
        self._uri(concept_id)  # ensures the concept exists in the ontology
        if concept_id not in self.mappings["concepts"]:
            raise KeyError(f"no database mapping for concept {concept_id!r}")
        spec = self.mappings["concepts"][concept_id]
        return {
            "concept_id": concept_id,
            "table": spec["table"],
            "column": spec["column"],
            "filters": dict(spec.get("filters", {})),
        }
