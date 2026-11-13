"""Validation for the Financial Ontology and its semantic mappings.

Two independent layers:

* Offline validation -- checks the RDF/Turtle syntax (already enforced by the
  parser), Concept ID uniqueness, English labels, valid broader relations,
  absence of classification cycles, domains, definition status, and the
  integrity of every semantic mapping. No database connection required.
* Database validation -- optionally connects to PostgreSQL via SQLAlchemy
  Inspector and verifies that every mapped schema/table/column/filter column
  actually exists and that the metric column type suits a financial value.

If no ``engine_url`` is supplied, database validation is reported as skipped
rather than passed.
"""
from __future__ import annotations

import re

from rdflib import Graph

from .loader import ALMC, ONTO, RDF, SKOS

# Strict PostgreSQL identifier rule: a single unquoted identifier. This rejects
# SQL fragments such as "nii || eve" or "scenario_code OR 1=1".
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SQL_DANGER = (";", "--", "/*", "*/", "(", ")", "\x00")


def _concept_ids(graph: Graph) -> set[str]:
    return {str(s).replace(str(ALMC), "")
            for s in graph.subjects(RDF["type"], SKOS["Concept"])}


def _find_cycles(graph: Graph, concept_ids: set[str]) -> list[list[str]]:
    """Detect cycles in the skos:broader hierarchy via DFS over all parents.

    A concept may have multiple broader parents, so every broader edge is
    followed; any path that returns to its start (or to an earlier node on the
    path) is reported as a cycle.
    """
    cycles: list[list[str]] = []
    seen_cycles: set[tuple[str, ...]] = set()
    for start in concept_ids:
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        visited: set[str] = {start}
        while stack:
            node, path = stack.pop()
            for broader in graph.objects(ALMC[node], SKOS["broader"]):
                parent = str(broader).replace(str(ALMC), "")
                if parent not in concept_ids:
                    continue
                if parent == start:
                    _record_cycle(cycles, seen_cycles, path + [start])
                elif parent in path:
                    idx = path.index(parent)
                    _record_cycle(cycles, seen_cycles, path[idx:] + [parent])
                elif parent not in visited:
                    visited.add(parent)
                    stack.append((parent, path + [parent]))
    return cycles


def _record_cycle(cycles: list[list[str]], seen: set[tuple[str, ...]],
                  cycle: list[str]) -> None:
    key = tuple(cycle)
    if key not in seen:
        seen.add(key)
        cycles.append(cycle)


def validate_offline(graph: Graph, mappings: dict) -> dict:
    """Validate ontology and mappings without touching any database."""
    o_err: list[str] = []
    o_warn: list[str] = []
    m_err: list[str] = []
    m_warn: list[str] = []

    concept_ids = _concept_ids(graph)

    # ---- Layer 1: ontology checks (section 9.1) ----
    for subj in graph.subjects(RDF["type"], SKOS["Concept"]):
        cid = str(subj).replace(str(ALMC), "")
        if not str(subj).startswith(str(ALMC)):
            o_err.append(f"concept {cid} is not under the stable ALMC namespace")
        prefs = list(graph.objects(subj, SKOS["prefLabel"]))
        if not prefs:
            o_err.append(f"concept {cid} has no skos:prefLabel")
        else:
            for pref in prefs:
                if pref.language != "en":
                    o_err.append(f"concept {cid} prefLabel is not English: {pref!r}")
        if not list(graph.objects(subj, ONTO["domain"])):
            o_err.append(f"concept {cid} has no onto:domain")
        statuses = list(graph.objects(subj, ONTO["definitionStatus"]))
        if not statuses:
            o_warn.append(f"concept {cid} has no onto:definitionStatus")
        elif str(statuses[0]) == "needs_review":
            o_warn.append(f"concept {cid} definition is needs_review "
                          "(financial definition unconfirmed)")
        for broader in graph.objects(subj, SKOS["broader"]):
            b_local = str(broader).replace(str(ALMC), "")
            if b_local not in concept_ids:
                o_err.append(f"concept {cid} has invalid broader concept: {b_local}")

    for cycle in _find_cycles(graph, concept_ids):
        o_err.append("circular classification: " + " -> ".join(cycle))

    # ---- Layer 2: mapping checks (section 9.2) ----
    concepts = mappings.get("concepts", {})
    if not isinstance(concepts, dict):
        m_err.append("mappings 'concepts' must be a mapping")
        concepts = {}
    seen_targets: dict[tuple, str] = {}
    for cid, spec in concepts.items():
        if cid not in concept_ids:
            m_err.append(f"mapping references unknown concept: {cid}")
            continue
        if not isinstance(spec, dict):
            m_err.append(f"mapping for {cid} must be a mapping")
            continue
        table = spec.get("table")
        column = spec.get("column")
        # table must be exactly "schema.table" with two safe identifiers
        if not isinstance(table, str) or table.count(".") != 1:
            m_err.append(f"mapping {cid} has invalid table name: {table!r}")
        else:
            schema_part, table_part = table.split(".")
            if not IDENTIFIER_RE.fullmatch(schema_part) or \
               not IDENTIFIER_RE.fullmatch(table_part):
                m_err.append(f"mapping {cid} has invalid table identifier: {table!r}")
        # column must be a single safe identifier (no SQL expressions)
        if not isinstance(column, str) or not IDENTIFIER_RE.fullmatch(column):
            m_err.append(f"mapping {cid} has invalid column identifier: {column!r}")
        filters = spec.get("filters", {})
        if filters is not None and not isinstance(filters, dict):
            m_err.append(f"mapping {cid} filters must be a mapping")
            filters = {}
        for fcol, fval in (filters or {}).items():
            if not isinstance(fcol, str) or not IDENTIFIER_RE.fullmatch(fcol):
                m_err.append(f"mapping {cid} has invalid filter column "
                             f"identifier: {fcol!r}")
            elif any(ch in str(fval) for ch in _SQL_DANGER):
                m_err.append(f"mapping {cid} filter value looks like SQL: "
                             f"{fcol}={fval!r}")
        target_key = (table, column,
                      tuple(sorted((k, str(v)) for k, v in (filters or {}).items())))
        if target_key in seen_targets:
            m_err.append(f"ambiguous mapping: {cid} and {seen_targets[target_key]} "
                         f"target the same {table}.{column} {filters}")
        else:
            seen_targets[target_key] = cid
        if "NII" in cid and column != "nii":
            m_warn.append(f"concept {cid} is an NII concept but does not map "
                          "to the 'nii' column")

    return {"ontology": {"errors": o_err, "warnings": o_warn},
            "mappings": {"errors": m_err, "warnings": m_warn}}


def validate_database(graph: Graph, mappings: dict, engine_url: str) -> dict:
    """Validate mapped PostgreSQL objects against a live database catalog."""
    from sqlalchemy import create_engine, inspect

    errors: list[str] = []
    warnings: list[str] = []
    try:
        engine = create_engine(engine_url)
        inspector = inspect(engine)
    except Exception as exc:  # connection/config failure
        return {"executed": True, "errors": [f"cannot connect to database: {exc}"],
                "warnings": warnings}

    schema_names = set(inspector.get_schema_names())
    for cid, spec in mappings.get("concepts", {}).items():
        table = spec.get("table")
        if not isinstance(table, str) or "." not in table:
            continue  # offline check already flagged the bad name
        schema, _, table_name = table.partition(".")
        if schema not in schema_names:
            errors.append(f"{cid}: schema {schema} does not exist")
            continue
        if table_name not in inspector.get_table_names(schema=schema):
            errors.append(f"{cid}: table {table} does not exist")
            continue
        columns = {c["name"]: c
                   for c in inspector.get_columns(table_name, schema=schema)}
        column = spec.get("column")
        if column not in columns:
            errors.append(f"{cid}: column {column} does not exist in {table}")
        else:
            ctype = str(columns[column]["type"]).upper()
            if not any(t in ctype for t in
                       ("NUMERIC", "DECIMAL", "INT", "FLOAT", "DOUBLE")):
                warnings.append(f"{cid}: column {table}.{column} type {ctype} "
                                "may not suit a financial metric")
        for fcol in (spec.get("filters") or {}):
            if fcol not in columns:
                errors.append(f"{cid}: filter column {fcol} does not exist "
                              f"in {table}")
    engine.dispose()
    return {"executed": True, "errors": errors, "warnings": warnings}


def validate(graph: Graph, mappings: dict, engine_url: str | None = None) -> dict:
    """Run offline validation, plus optional database validation."""
    offline = validate_offline(graph, mappings)
    if engine_url:
        database = validate_database(graph, mappings, engine_url)
    else:
        database = {"executed": False, "errors": [],
                    "warnings": ["database validation skipped (no connection supplied)"]}
    ok = (not offline["ontology"]["errors"] and not offline["mappings"]["errors"]
          and not database["errors"])
    return {"ok": ok, **offline, "database": database}
