import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator
from validator import ProtocolValidationError, _validator_for, validate_bundle, validate_document


def observation(identifier="obs-1"):
    return {
        "schema_version": "1.1.0",
        "observation_id": identifier,
        "source": {"source_id": "source-a", "uri": "https://example.org/source"},
        "observed_at": "2026-11-17T12:00:00Z",
        "content": {"media_type": "text/plain", "text": "Observed text"},
        "integrity": {
            "algorithm": "sha-256",
            "scope": "content.text.utf8",
            "digest": hashlib.sha256(b"Observed text").hexdigest(),
        },
    }



def observation_v12(identifier="obs-1"):
    item = observation(identifier)
    item["schema_version"] = "1.2.0"
    item["collected_at"] = "2026-11-17T12:01:00Z"
    representation = b'{"content":"Observed text"}\\n'
    item["ingestion_provenance"] = {
        "component": "elite-ingestion-core",
        "component_version": "0.2.0",
        "adapter_version": "0.1.0",
        "import_id": "import-1",
        "record_id": "import-1:1",
        "source_record": 1,
        "source_format": "jsonl",
        "record_representation": {
            "algorithm": "sha-256",
            "scope": "jsonl.raw_line.bytes",
            "digest": hashlib.sha256(representation).hexdigest(),
            "size_bytes": len(representation),
        },
        "source_registry_revision": "registry-sha256:abc123",
    }
    return item


def claim(refs=None):
    return {
        "schema_version": "1.0.0",
        "claim_id": "claim-1",
        "proposition": "A bounded test proposition.",
        "evidence_refs": refs if refs is not None else ["obs-1"],
        "assessment": {"status": "unreviewed", "rationale": "Awaiting review"},
    }


def decision(subject="claim:claim-1"):
    return {
        "schema_version": "1.0.0",
        "decision_id": "decision-1",
        "subject_ref": subject,
        "decision": "defer",
        "reviewed_at": "2026-11-17T12:00:00Z",
        "reviewer_type": "human",
        "rationale": "Insufficient evidence for a decision.",
    }


class ProtocolConformanceTests(unittest.TestCase):
    def test_valid_bundle(self):
        validate_bundle([observation()], [claim()], [decision()])


    def test_observation_digest_mismatch_rejected(self):
        item = observation()
        item["integrity"]["digest"] = "a" * 64
        with self.assertRaisesRegex(ProtocolValidationError, "integrity digest mismatch"):
            validate_document("observation", item)

    def test_observation_text_mutation_requires_new_digest(self):
        item = observation()
        item["content"]["text"] = "Changed text"
        with self.assertRaisesRegex(ProtocolValidationError, "integrity digest mismatch"):
            validate_document("observation", item)

    def test_observation_integrity_scope_is_required(self):
        item = observation()
        del item["integrity"]["scope"]
        with self.assertRaises(ProtocolValidationError):
            validate_document("observation", item)

    def test_observation_integrity_scope_is_fixed(self):
        item = observation()
        item["integrity"]["scope"] = "whole-source-file"
        with self.assertRaises(ProtocolValidationError):
            validate_document("observation", item)


    def test_valid_observation_v1_2_with_ingestion_provenance(self):
        validate_document("observation", observation_v12())

    def test_observation_v1_2_requires_ingestion_provenance(self):
        item = observation_v12()
        del item["ingestion_provenance"]
        with self.assertRaises(ProtocolValidationError):
            validate_document("observation", item)

    def test_observation_v1_2_requires_collected_at(self):
        item = observation_v12()
        del item["collected_at"]
        with self.assertRaises(ProtocolValidationError):
            validate_document("observation", item)

    def test_observation_v1_2_rejects_unknown_representation_scope(self):
        item = observation_v12()
        item["ingestion_provenance"]["record_representation"]["scope"] = "whole-file"
        with self.assertRaises(ProtocolValidationError):
            validate_document("observation", item)

    def test_observation_v1_2_keeps_representation_and_text_digests_distinct(self):
        item = observation_v12()
        representation_digest = item["ingestion_provenance"]["record_representation"]["digest"]
        text_digest = item["integrity"]["digest"]
        self.assertNotEqual(representation_digest, text_digest)
        validate_document("observation", item)


    def test_observation_v1_2_representation_scope_must_match_source_format(self):
        item = observation_v12()
        item["ingestion_provenance"]["source_format"] = "csv"
        with self.assertRaisesRegex(ProtocolValidationError, "does not match source_format"):
            validate_document("observation", item)

    def test_unknown_observation_schema_version_rejected(self):
        item = observation()
        item["schema_version"] = "9.9.9"
        with self.assertRaisesRegex(ProtocolValidationError, "unsupported observation schema version"):
            validate_document("observation", item)

    def test_review_decision_requires_schema_version(self):
        item = decision()
        del item["schema_version"]
        with self.assertRaises(ProtocolValidationError):
            validate_document("review_decision", item)

    def test_invalid_datetime_rejected(self):
        item = observation()
        item["observed_at"] = "yesterday"
        with self.assertRaises(ProtocolValidationError):
            validate_document("observation", item)

    def test_unresolved_evidence_reference_rejected(self):
        with self.assertRaisesRegex(ProtocolValidationError, "unresolved evidence_refs"):
            validate_bundle([observation()], [claim(["missing-observation"])])

    def test_duplicate_evidence_refs_rejected_by_schema(self):
        with self.assertRaises(ProtocolValidationError):
            validate_document("claim", claim(["obs-1", "obs-1"]))

    def test_unresolved_review_subject_rejected(self):
        with self.assertRaisesRegex(ProtocolValidationError, "unresolved subject_ref"):
            validate_bundle([observation()], [claim()], [decision("claim:missing")])

    def test_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(ProtocolValidationError, "duplicate observation_id"):
            validate_bundle([observation(), observation()], [claim()])

    def test_non_object_document_rejected_cleanly(self):
        with self.assertRaisesRegex(ProtocolValidationError, "must be an object"):
            validate_document("observation", ["not", "an", "object"])

    def test_non_object_bundle_item_rejected_cleanly(self):
        with self.assertRaisesRegex(ProtocolValidationError, "must be an object"):
            validate_bundle([None], [])

    def test_bundle_materialization_is_bounded(self):
        def observations():
            yield observation("obs-1")
            yield observation("obs-2")
            yield observation("obs-3")

        with patch("validator.MAX_BUNDLE_ITEMS_PER_KIND", 2):
            with self.assertRaisesRegex(ProtocolValidationError, "exceeds 2 item limit"):
                validate_bundle(observations(), [])

    def test_claim_evidence_collection_has_a_schema_limit(self):
        item = claim([f"obs-{index}" for index in range(257)])
        with self.assertRaises(ProtocolValidationError):
            validate_document("claim", item)

    def test_all_schema_documents_are_valid_draft_2020_12(self):
        schema_dir = Path(__file__).resolve().parents[1] / "schemas"
        for filename in (
            "observation.schema.json",
            "observation-v1.2.0.schema.json",
            "claim.schema.json",
            "review-decision.schema.json",
        ):
            with self.subTest(schema=filename):
                schema = json.loads((schema_dir / filename).read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)

    def test_non_iterable_bundle_section_rejected_cleanly(self):
        with self.assertRaisesRegex(ProtocolValidationError, "must be an iterable"):
            validate_bundle(None, [])

    def test_observation_source_metadata_is_bounded(self):
        item = observation()
        item["source"]["source_id"] = "s" * 257
        with self.assertRaises(ProtocolValidationError):
            validate_document("observation", item)

    def test_compiled_schema_validator_is_cached(self):
        first = _validator_for("observation")
        second = _validator_for("observation")
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
