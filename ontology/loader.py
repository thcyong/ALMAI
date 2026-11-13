"""Load the Financial Ontology (SKOS/Turtle) and its semantic mappings (YAML).

Both artifacts are data files shipped with this package. Loading is
side-effect free and requires no database connection.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, Namespace

PACKAGE_DIR = Path(__file__).resolve().parent

DEFAULT_ONTOLOGY = PACKAGE_DIR / "banking.ttl"
DEFAULT_MAPPINGS = PACKAGE_DIR / "mappings.yaml"

# SKOS core vocabulary used by the ontology.
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
# RDF syntax vocabulary (rdf:type), used to find Concepts declared with "a".
RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
# Custom ALMAI ontology properties (domain, definition status, ...).
ONTO = Namespace("https://almai.example/ontology/ontology.ttl#")
# Stable Concept ID namespace. Concept URI = ALMC + "<ConceptID>".
ALMC = Namespace("https://almai.example/ontology/concept/")


def load_ontology(path: Path | str = DEFAULT_ONTOLOGY) -> Graph:
    """Parse the SKOS Turtle ontology into an in-memory RDF graph."""
    graph = Graph()
    graph.parse(str(path), format="turtle")
    return graph


def _strict_yaml_load(stream: Any) -> dict[str, Any]:
    """Load YAML with duplicate-key rejection.

    Reuses ``data_etl``'s ``_DatasetLoader`` (from ``bank_etl.config``) so the
    Ontology and the ETL share one validated YAML contract instead of two
    divergent implementations. That loader overrides ``construct_mapping`` to
    raise on duplicate keys and disables YAML 1.1's implicit bool coercion.
    """
    src = Path(__file__).resolve().parents[1] / "data_etl" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from bank_etl.config import _DatasetLoader
    except Exception as exc:  # pragma: no cover - depends on sibling project
        raise RuntimeError(
            "Unable to import data_etl's _DatasetLoader for strict YAML parsing: "
            f"{exc}. data_etl must be present to reuse its duplicate-key check."
        ) from exc
    return yaml.load(stream, Loader=_DatasetLoader)


def load_mappings(path: Path | str = DEFAULT_MAPPINGS) -> dict[str, Any]:
    """Parse the semantic mapping YAML (Concept ID -> PostgreSQL target).

    Uses the strict loader so a duplicated Concept ID in ``concepts:`` raises
    instead of being silently overwritten.
    """
    with open(path, encoding="utf-8") as handle:
        data = _strict_yaml_load(handle)
    if not isinstance(data, dict) or "concepts" not in data:
        raise ValueError("mappings file must contain a top-level 'concepts' mapping")
    if not isinstance(data["concepts"], dict):
        raise ValueError("'concepts' must be a mapping of Concept ID to target")
    return data
