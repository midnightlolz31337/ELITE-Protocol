import unittest
from validator import ProtocolValidationError, validate_bundle, validate_document


def observation(identifier="obs-1"):
    return {
        "schema_version": "1.0.0",
        "observation_id": identifier,
        "source": {"source_id": "source-a", "uri": "https://example.org/source"},
        "observed_at": "2026-11-17T12:00:00Z",
        "content": {"media_type": "text/plain", "text": "Observed text"},
        "integrity": {"algorithm": "sha-256", "digest": "a" * 64},
    }


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


if __name__ == "__main__":
    unittest.main()
