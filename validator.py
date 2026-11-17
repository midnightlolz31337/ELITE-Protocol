"""JSON Schema and cross-record validation for ELITE protocol bundles."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
SCHEMA_DIR = ROOT / "schemas"
SCHEMA_FILES = {
    "observation": "observation.schema.json",
    "claim": "claim.schema.json",
    "review_decision": "review-decision.schema.json",
}


class ProtocolValidationError(ValueError):
    """Raised when a protocol document or bundle violates conformance."""


MAX_BUNDLE_ITEMS_PER_KIND = 10_000


def _bounded_items(items: Iterable[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    """Materialize a bounded bundle section; never consume an unbounded iterator."""
    result = []
    for index, item in enumerate(items):
        if index >= MAX_BUNDLE_ITEMS_PER_KIND:
            raise ProtocolValidationError(
                f"{kind} bundle exceeds {MAX_BUNDLE_ITEMS_PER_KIND} item limit"
            )
        if not isinstance(item, Mapping):
            raise ProtocolValidationError(f"{kind} bundle item {index} must be an object")
        result.append(item)
    return result


def _load_schema(kind: str) -> dict:
    try:
        path = SCHEMA_DIR / SCHEMA_FILES[kind]
    except KeyError as exc:
        raise ValueError(f"unknown document kind: {kind}") from exc
    return json.loads(path.read_text(encoding="utf-8"))


def validate_document(kind: str, document: Mapping[str, Any]) -> None:
    if not isinstance(document, Mapping):
        raise ProtocolValidationError(f"{kind} document must be an object")
    schema = _load_schema(kind)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda err: list(err.absolute_path))
    if errors:
        details = "; ".join(
            f"{'.'.join(map(str, err.absolute_path)) or '<root>'}: {err.message}"
            for err in errors
        )
        raise ProtocolValidationError(f"{kind} is not conformant: {details}")


def validate_bundle(
    observations: Iterable[Mapping[str, Any]],
    claims: Iterable[Mapping[str, Any]],
    review_decisions: Iterable[Mapping[str, Any]] = (),
) -> None:
    """Validate documents and ensure all claim/review references resolve in-bundle.

    Reference syntax is deliberately explicit: observation:<id> or claim:<id>.
    This validates referential integrity, not truth, authenticity, or authorization.
    """
    observations = _bounded_items(observations, "observations")
    claims = _bounded_items(claims, "claims")
    decisions = _bounded_items(review_decisions, "review_decisions")

    observation_ids: set[str] = set()
    claim_ids: set[str] = set()
    for item in observations:
        validate_document("observation", item)
        identifier = item["observation_id"]
        if identifier in observation_ids:
            raise ProtocolValidationError(f"duplicate observation_id: {identifier}")
        observation_ids.add(identifier)

    for item in claims:
        validate_document("claim", item)
        identifier = item["claim_id"]
        if identifier in claim_ids:
            raise ProtocolValidationError(f"duplicate claim_id: {identifier}")
        claim_ids.add(identifier)

    for item in claims:
        missing = [ref for ref in item["evidence_refs"] if ref not in observation_ids]
        if missing:
            raise ProtocolValidationError(
                f"claim {item['claim_id']} has unresolved evidence_refs: {missing}"
            )

    known_subjects = {f"observation:{value}" for value in observation_ids}
    known_subjects.update(f"claim:{value}" for value in claim_ids)
    decision_ids: set[str] = set()
    for item in decisions:
        validate_document("review_decision", item)
        identifier = item["decision_id"]
        if identifier in decision_ids:
            raise ProtocolValidationError(f"duplicate decision_id: {identifier}")
        decision_ids.add(identifier)
        if item["subject_ref"] not in known_subjects:
            raise ProtocolValidationError(
                f"review decision {identifier} has unresolved subject_ref: {item['subject_ref']}"
            )
