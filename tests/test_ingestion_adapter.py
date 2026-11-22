import hashlib
import os
import subprocess
import sys
import json
import tempfile
import unittest
from pathlib import Path

from adapters.ingestion_v1 import (
    IngestionAdapterError,
    iter_accepted_jsonl,
    iter_current_generation,
    export_current_generation,
    observation_from_envelope,
)


def envelope(*, content="Captured text", decision="accepted", source_format="jsonl", source_format_digest=None):
    return {
        "record_id": "import-123:4",
        "import_id": "import-123",
        "source_id": "source-example",
        "source_format": source_format,
        "source_record": 4,
        "content_sha256": source_format_digest or hashlib.sha256(b'{"content":"Captured text"}\n').hexdigest(),
        "raw_size_bytes": 28,
        "record": {"content": content},
        "decision": decision,
        "reasons": [],
    }


class IngestionAdapterTests(unittest.TestCase):
    def kwargs(self):
        return {
            "source_uri": "https://example.org/archive/item",
            "collected_at": "2026-11-22T12:30:00Z",
            "observed_at": "2026-11-22T12:00:00Z",
        }

    def test_adapts_accepted_envelope_and_validates_protocol_schema(self):
        item = observation_from_envelope(envelope(), **self.kwargs())
        self.assertEqual(item["schema_version"], "1.1.0")
        self.assertEqual(item["observation_id"], "import-123:4")
        self.assertEqual(item["source"]["source_id"], "source-example")
        self.assertEqual(item["source"]["uri"], "https://example.org/archive/item")
        self.assertEqual(item["ingestion"]["import_id"], "import-123")
        self.assertEqual(item["ingestion"]["source_record_line"], 4)
        self.assertEqual(item["ingestion"]["source_format"], "jsonl")
        self.assertEqual(item["integrity"]["scope"], "content.text.utf8")
        self.assertEqual(item["integrity"]["digest"], hashlib.sha256(b"Captured text").hexdigest())

    def test_preserves_ingestion_digest_separately_from_text_digest(self):
        raw_digest = envelope()["content_sha256"]
        item = observation_from_envelope(envelope(), **self.kwargs())
        self.assertEqual(item["ingestion"]["record_digest"]["digest"], raw_digest)
        self.assertNotEqual(item["integrity"]["digest"], raw_digest)
        self.assertEqual(item["ingestion"]["record_digest"]["scope"], "ingestion.jsonl.line.bytes")

    def test_csv_digest_is_explicitly_labeled_normalized_row_not_raw_bytes(self):
        item = observation_from_envelope(envelope(source_format="csv"), **self.kwargs())
        self.assertEqual(
            item["ingestion"]["record_digest"]["scope"],
            "ingestion.csv.normalized_row.utf8",
        )
        self.assertTrue(any("normalized row" in value for value in item["limitations"]))

    def test_quarantined_envelope_never_becomes_observation(self):
        with self.assertRaisesRegex(IngestionAdapterError, "only accepted"):
            observation_from_envelope(envelope(decision="quarantine"), **self.kwargs())

    def test_missing_observed_at_is_not_inferred(self):
        with self.assertRaisesRegex(IngestionAdapterError, "observed_at is absent"):
            observation_from_envelope(envelope(), **{k: v for k, v in self.kwargs().items() if k != "observed_at"})

    def test_record_timestamp_takes_precedence_when_explicit(self):
        item = envelope()
        item["record"]["observed_at"] = "2026-11-21T09:00:00Z"
        result = observation_from_envelope(item, **self.kwargs())
        self.assertEqual(result["observed_at"], "2026-11-21T09:00:00Z")

    def test_missing_source_uri_fails_closed(self):
        with self.assertRaisesRegex(IngestionAdapterError, "source_uri"):
            observation_from_envelope(envelope(), **{**self.kwargs(), "source_uri": ""})


    def test_unknown_envelope_source_format_fails_closed(self):
        item = envelope(source_format="ambiguous")
        with self.assertRaisesRegex(IngestionAdapterError, "source_format"):
            observation_from_envelope(item, **self.kwargs())

    def test_missing_envelope_source_format_fails_closed(self):
        item = envelope()
        del item["source_format"]
        with self.assertRaisesRegex(IngestionAdapterError, "source_format"):
            observation_from_envelope(item, **self.kwargs())

    def test_invalid_digest_fails_closed(self):
        item = envelope()
        item["content_sha256"] = "not-a-digest"
        with self.assertRaisesRegex(IngestionAdapterError, "SHA-256"):
            observation_from_envelope(item, **self.kwargs())

    def test_accepted_jsonl_stream_is_converted_incrementally(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accepted.jsonl"
            path.write_text(json.dumps(envelope()) + "\n" + json.dumps(envelope(content="Second")) + "\n")
            items = list(iter_accepted_jsonl(path, **self.kwargs()))
            self.assertEqual([item["content"]["text"] for item in items], ["Captured text", "Second"])

    def test_malformed_jsonl_stream_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accepted.jsonl"
            path.write_text('{"decision":\n')
            with self.assertRaisesRegex(IngestionAdapterError, "invalid JSON"):
                list(iter_accepted_jsonl(path, **self.kwargs()))


    def test_current_pointer_verifies_generation_before_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generation_id = "12345678-1234-5678-1234-567812345678"
            generation = root / "generations" / generation_id
            generation.mkdir(parents=True)
            accepted = (json.dumps(envelope()) + "\n").encode()
            quarantine = b""
            (generation / "accepted.jsonl").write_bytes(accepted)
            (generation / "quarantine.jsonl").write_bytes(quarantine)
            manifest = {
                "schema_version": "1",
                "generation_id": generation_id,
                "generation_path": f"generations/{generation_id}",
                "created_at": "2026-11-22T12:30:00Z",
                "accepted_count": 1,
                "quarantine_count": 0,
                "files": {
                    "accepted.jsonl": {
                        "path": f"generations/{generation_id}/accepted.jsonl",
                        "size": len(accepted),
                        "sha256": hashlib.sha256(accepted).hexdigest(),
                    },
                    "quarantine.jsonl": {
                        "path": f"generations/{generation_id}/quarantine.jsonl",
                        "size": len(quarantine),
                        "sha256": hashlib.sha256(quarantine).hexdigest(),
                    },
                },
            }
            pointer = root / "CURRENT.json"
            pointer.write_text(json.dumps(manifest))
            items = list(iter_current_generation(pointer, **self.kwargs()))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["content"]["text"], "Captured text")

    def test_current_pointer_rejects_tampered_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generation_id = "12345678-1234-5678-1234-567812345678"
            generation = root / "generations" / generation_id
            generation.mkdir(parents=True)
            accepted = (json.dumps(envelope()) + "\n").encode()
            (generation / "accepted.jsonl").write_bytes(accepted)
            (generation / "quarantine.jsonl").write_bytes(b"")
            manifest = {
                "schema_version": "1", "generation_id": generation_id,
                "generation_path": f"generations/{generation_id}",
                "created_at": "2026-11-22T12:30:00Z", "accepted_count": 1,
                "quarantine_count": 0,
                "files": {
                    name: {
                        "path": f"generations/{generation_id}/{name}",
                        "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                    }
                    for name, data in (("accepted.jsonl", accepted), ("quarantine.jsonl", b""))
                },
            }
            pointer = root / "CURRENT.json"
            pointer.write_text(json.dumps(manifest))
            (generation / "accepted.jsonl").write_text("tampered")
            with self.assertRaisesRegex(IngestionAdapterError, "integrity check failed"):
                list(iter_current_generation(pointer, **self.kwargs()))


    @unittest.skipUnless(os.environ.get("ELITE_INGESTION_CORE_PATH"), "requires pinned Ingestion Core checkout")
    def test_real_ingestion_core_jsonl_output_round_trips_through_adapter(self):
        core_path = Path(os.environ["ELITE_INGESTION_CORE_PATH"]).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            source_bytes = b'{"content":"Cross-repository JSONL evidence"}\n'
            source.write_bytes(source_bytes)
            output = root / "output"
            subprocess.run(
                [
                    sys.executable, "-m", "elite_ingestion.cli", "ingest",
                    str(source), "--source-id", "integration-source",
                    "--operator-asserts-authorized", "--output-dir", str(output),
                ],
                cwd=core_path, check=True, capture_output=True, text=True,
            )
            observations = list(iter_current_generation(
                output / "CURRENT.json",
                source_uri="https://example.org/integration/jsonl",
                collected_at="2026-11-22T12:30:00Z",
                observed_at="2026-11-22T12:00:00Z",
            ))
            self.assertEqual(len(observations), 1)
            item = observations[0]
            self.assertEqual(item["content"]["text"], "Cross-repository JSONL evidence")
            self.assertEqual(item["ingestion"]["record_digest"]["digest"], hashlib.sha256(source_bytes).hexdigest())
            self.assertEqual(item["ingestion"]["record_digest"]["size_bytes"], len(source_bytes))
            self.assertEqual(item["ingestion"]["record_digest"]["scope"], "ingestion.jsonl.line.bytes")

    @unittest.skipUnless(os.environ.get("ELITE_INGESTION_CORE_PATH"), "requires pinned Ingestion Core checkout")
    def test_real_ingestion_core_csv_output_labels_normalized_row_digest(self):
        core_path = Path(os.environ["ELITE_INGESTION_CORE_PATH"]).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_text("content\nCSV generated evidence\n", encoding="utf-8")
            output = root / "output"
            subprocess.run(
                [
                    sys.executable, "-m", "elite_ingestion.cli", "ingest",
                    str(source), "--source-id", "integration-source",
                    "--operator-asserts-authorized", "--output-dir", str(output),
                ],
                cwd=core_path, check=True, capture_output=True, text=True,
            )
            observations = list(iter_current_generation(
                output / "CURRENT.json",
                source_uri="https://example.org/integration/csv",
                collected_at="2026-11-22T12:30:00Z",
                observed_at="2026-11-22T12:00:00Z",
            ))
            self.assertEqual(len(observations), 1)
            item = observations[0]
            expected_row = b'["CSV generated evidence"]'
            self.assertEqual(item["ingestion"]["record_digest"]["digest"], hashlib.sha256(expected_row).hexdigest())
            self.assertEqual(item["ingestion"]["record_digest"]["scope"], "ingestion.csv.normalized_row.utf8")
            self.assertNotEqual(item["ingestion"]["record_digest"]["digest"], hashlib.sha256(source.read_bytes()).hexdigest())


    def test_current_pointer_rejects_record_count_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generation_id = "12345678-1234-5678-1234-567812345678"
            generation = root / "generations" / generation_id
            generation.mkdir(parents=True)
            accepted = (json.dumps(envelope()) + "\n").encode()
            quarantine = b""
            (generation / "accepted.jsonl").write_bytes(accepted)
            (generation / "quarantine.jsonl").write_bytes(quarantine)
            manifest = {
                "schema_version": "1", "generation_id": generation_id,
                "generation_path": f"generations/{generation_id}",
                "created_at": "2026-11-22T12:30:00Z", "accepted_count": 2,
                "quarantine_count": 0,
                "files": {
                    name: {
                        "path": f"generations/{generation_id}/{name}",
                        "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                    }
                    for name, data in (("accepted.jsonl", accepted), ("quarantine.jsonl", quarantine))
                },
            }
            pointer = root / "CURRENT.json"
            pointer.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(IngestionAdapterError, "record count mismatch"):
                list(iter_current_generation(pointer, **self.kwargs()))


    def _write_current_fixture(self, root, item):
        generation_id = "12345678-1234-5678-1234-567812345678"
        generation = root / "generations" / generation_id
        generation.mkdir(parents=True)
        accepted = (json.dumps(item) + "\n").encode()
        quarantine = b""
        (generation / "accepted.jsonl").write_bytes(accepted)
        (generation / "quarantine.jsonl").write_bytes(quarantine)
        manifest = {
            "schema_version": "1", "generation_id": generation_id,
            "generation_path": f"generations/{generation_id}",
            "created_at": "2026-11-22T12:30:00Z", "accepted_count": 1,
            "quarantine_count": 0,
            "files": {
                name: {
                    "path": f"generations/{generation_id}/{name}",
                    "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                }
                for name, data in (("accepted.jsonl", accepted), ("quarantine.jsonl", quarantine))
            },
        }
        pointer = root / "CURRENT.json"
        pointer.write_text(json.dumps(manifest))
        return pointer, generation


    def test_current_pointer_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pointer, _ = self._write_current_fixture(root, envelope())
            pointer.write_text('{"schema_version":"1","schema_version":"1"}')
            with self.assertRaisesRegex(IngestionAdapterError, "duplicate JSON key"):
                list(iter_current_generation(pointer, **self.kwargs()))

    def test_current_pointer_rejects_timezone_free_created_at(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pointer, _ = self._write_current_fixture(root, envelope())
            manifest = json.loads(pointer.read_text())
            manifest["created_at"] = "2026-11-22T12:30:00"
            pointer.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(IngestionAdapterError, "must include a timezone"):
                list(iter_current_generation(pointer, **self.kwargs()))

    def test_export_current_generation_is_deterministic_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pointer, _ = self._write_current_fixture(root, envelope())
            output = root / "export" / "observations.jsonl"
            options = {
                "source_uri": "https://example.org/archive/item",
                "collected_at": "2026-11-22T12:30:00Z",
                "observed_at": "2026-11-22T12:00:00Z",
            }
            self.assertEqual(export_current_generation(pointer, output, **options), 1)
            first = output.read_bytes()
            self.assertTrue(first.endswith(b"\n"))
            self.assertEqual(export_current_generation(pointer, output, **options), 1)
            self.assertEqual(output.read_bytes(), first)
            exported = json.loads(first.decode("utf-8"))
            self.assertEqual(exported["content"]["text"], "Captured text")
            self.assertEqual(exported["ingestion"]["source_format"], "jsonl")

    def test_export_failure_preserves_previous_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = envelope()
            pointer, _ = self._write_current_fixture(root, item)
            output = root / "observations.jsonl"
            output.write_bytes(b"previous committed export\n")
            with self.assertRaisesRegex(IngestionAdapterError, "observed_at is absent"):
                export_current_generation(
                    pointer, output,
                    source_uri="https://example.org/archive/item",
                    collected_at="2026-11-22T12:30:00Z",
                )
            self.assertEqual(output.read_bytes(), b"previous committed export\n")
            self.assertEqual(list(root.glob(".elite-observation-export-*.tmp")), [])

    def test_export_refuses_destination_inside_source_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pointer, generation = self._write_current_fixture(root, envelope())
            with self.assertRaisesRegex(IngestionAdapterError, "outside the current generation"):
                export_current_generation(
                    pointer, generation / "converted.jsonl", **self.kwargs()
                )


if __name__ == "__main__":
    unittest.main()
