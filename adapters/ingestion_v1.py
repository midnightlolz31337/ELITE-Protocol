"""Fail-closed adapter from ELITE Ingestion Core envelopes to Observation 1.1.0.

The adapter preserves the ingestion record digest separately from the
Observation content.text digest. It never promotes quarantined envelopes.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from validator import validate_document
from elite_ingestion.generation import read_current_generation

SCHEMA_VERSION = "1.1.0"
SOURCE_DIGEST_SCOPES = {
    "jsonl": "jsonl.raw_line.bytes",
    "csv": "csv.parsed_row.canonical_json.utf8",
}


class IngestionAdapterError(ValueError):
    """Raised when an ingestion envelope cannot be safely adapted."""


def observation_from_envelope(
    envelope: Mapping[str, Any],
    *,
    source_uri: str,
    collected_at: str,
    observed_at: str | None = None,
    media_type: str = "text/plain",
    language: str | None = None,
) -> dict[str, Any]:
    """Convert one accepted envelope; timestamps and source URI are caller supplied.

    If the source record contains an explicit string `observed_at`, it takes
    precedence over the optional argument. No timestamp is inferred.
    """
    if not isinstance(envelope, Mapping):
        raise IngestionAdapterError("ingestion envelope must be an object")
    if envelope.get("decision") != "accepted":
        raise IngestionAdapterError("only accepted ingestion envelopes may become observations")
    if envelope.get("reasons") not in ([], None):
        raise IngestionAdapterError("accepted envelope contains decision reasons")
    record = envelope.get("record")
    if not isinstance(record, Mapping):
        raise IngestionAdapterError("accepted envelope record must be an object")

    source_id = envelope.get("source_id")
    import_id = envelope.get("import_id")
    record_id = envelope.get("record_id")
    source_line = envelope.get("source_record")
    digest = envelope.get("record_representation_sha256")
    size_bytes = envelope.get("record_representation_size_bytes")
    for name, value in (("source_id", source_id), ("import_id", import_id), ("record_id", record_id)):
        if not isinstance(value, str) or not value.strip():
            raise IngestionAdapterError(f"missing or invalid {name}")
    if isinstance(source_line, bool) or not isinstance(source_line, int) or source_line < 1:
        raise IngestionAdapterError("source_record must be a positive line number")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise IngestionAdapterError("record_representation_sha256 must be a lowercase SHA-256 hex digest")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise IngestionAdapterError("record_representation_size_bytes must be a non-negative integer")
    source_format = envelope.get("source_format")
    if not isinstance(source_format, str) or source_format not in SOURCE_DIGEST_SCOPES:
        raise IngestionAdapterError("ingestion envelope source_format must be jsonl or csv")
    if envelope.get("record_representation_scope") != SOURCE_DIGEST_SCOPES[source_format]:
        raise IngestionAdapterError("record representation scope does not match source_format")
    if record_id != f"{import_id}:{source_line}":
        raise IngestionAdapterError("record_id does not match import_id and source_record")
    if not isinstance(source_uri, str) or not source_uri.strip():
        raise IngestionAdapterError("source_uri must be explicitly supplied")
    if not isinstance(collected_at, str) or not collected_at.strip():
        raise IngestionAdapterError("collected_at must be explicitly supplied")
    if not isinstance(media_type, str) or not media_type.strip():
        raise IngestionAdapterError("media_type must be a non-empty string")

    content = record.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, Mapping) and isinstance(content.get("text"), str):
        text = content["text"]
    else:
        raise IngestionAdapterError("record content must be a string or an object with string text")

    record_observed_at = record.get("observed_at")
    timestamp = record_observed_at if isinstance(record_observed_at, str) and record_observed_at else observed_at
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise IngestionAdapterError(
            "observed_at is absent; supply an explicit observed_at value rather than inferring one"
        )

    source_digest_scope = SOURCE_DIGEST_SCOPES[source_format]
    limitations = [
        "Ingestion record digest is integrity metadata, not source authentication or proof of truth."
    ]
    if source_format == "csv":
        limitations.append(
            "CSV digest covers the ingestion core's canonical JSON array of parsed row fields, not original source-file or physical-row bytes."
        )
    else:
        limitations.append(
            "JSONL digest covers the exact physical line bytes read by ingestion, including its line terminator when present; it is not a whole-file digest."
        )

    observation: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "observation_id": record_id,
        "source": {"source_id": source_id, "uri": source_uri},
        "observed_at": timestamp,
        "collected_at": collected_at,
        "content": {"media_type": media_type, "text": text},
        "integrity": {
            "algorithm": "sha-256",
            "scope": "content.text.utf8",
            "digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
        "ingestion": {
            "import_id": import_id,
            "record_id": record_id,
            "source_format": source_format,
            "source_record_line": source_line,
            "record_digest": {
                "algorithm": "sha-256",
                "scope": source_digest_scope,
                "digest": digest,
                "size_bytes": size_bytes,
            },
        },
        "limitations": limitations,
    }
    if language is not None:
        if not isinstance(language, str) or not language:
            raise IngestionAdapterError("language must be a non-empty string when supplied")
        observation["content"]["language"] = language

    try:
        validate_document("observation", observation)
    except Exception as exc:
        raise IngestionAdapterError(f"adapted observation failed Protocol validation: {exc}") from exc
    return observation




def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise IngestionAdapterError(f"duplicate JSON key in accepted envelope: {key}")
        result[key] = value
    return result


def _verified_current_generation(pointer_path: str | Path) -> tuple[dict[str, Any], Path]:
    try:
        return read_current_generation(Path(pointer_path))
    except Exception as exc:
        raise IngestionAdapterError(
            f"cannot resolve a verified committed Ingestion Core generation: {exc}"
        ) from exc


def accepted_jsonl_from_current(pointer_path: str | Path) -> Path:
    """Resolve accepted.jsonl using Ingestion Core's public generation reader."""
    _manifest, generation = _verified_current_generation(pointer_path)
    return generation / "accepted.jsonl"


def iter_current_generation(pointer_path: str | Path, **adapter_options: Any) -> Iterator[dict[str, Any]]:
    """Stream observations from the verified generation named by CURRENT.json."""
    manifest, generation = _verified_current_generation(pointer_path)
    accepted_entry = manifest["files"]["accepted.jsonl"]
    yield from iter_accepted_jsonl(
        generation / "accepted.jsonl",
        expected_import_id=manifest["generation_id"],
        expected_digest=accepted_entry["sha256"],
        expected_size=accepted_entry["size"],
        expected_count=manifest["accepted_count"],
        **adapter_options,
    )


def iter_accepted_jsonl(
    path: str | Path,
    *,
    source_uri: str,
    collected_at: str,
    observed_at: str | None = None,
    media_type: str = "text/plain",
    language: str | None = None,
    expected_import_id: str | None = None,
    expected_digest: str | None = None,
    expected_size: int | None = None,
    expected_count: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Read, re-verify, then stream a bounded accepted.jsonl file.

    Generation-pointer verification happens before this function is called.
    The second digest/size/count check closes the validation-to-use gap if a
    generation file changes between pointer validation and conversion.
    """
    accepted_path = Path(path)
    max_bytes = 5 * 1024 * 1024
    with accepted_path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
        if len(data) > max_bytes or handle.read(1):
            raise IngestionAdapterError("accepted envelope stream exceeds the 5 MiB limit")
    if expected_size is not None and len(data) != expected_size:
        raise IngestionAdapterError("accepted envelope stream size changed after CURRENT validation")
    if expected_digest is not None and hashlib.sha256(data).hexdigest() != expected_digest:
        raise IngestionAdapterError("accepted envelope stream digest changed after CURRENT validation")
    if data and not data.endswith(b"\n"):
        raise IngestionAdapterError("accepted envelope stream is not newline-terminated")
    line_count = data.count(b"\n")
    if expected_count is not None and line_count != expected_count:
        raise IngestionAdapterError("accepted envelope stream count changed after CURRENT validation")

    for line_number, raw_line in enumerate(data.splitlines(), 1):
        if not raw_line.strip():
            raise IngestionAdapterError(f"blank line in accepted envelope stream at line {line_number}")
        try:
            line = raw_line.decode("utf-8")
            envelope = json.loads(line, object_pairs_hook=_unique_json_object)
        except UnicodeDecodeError as exc:
            raise IngestionAdapterError(
                f"invalid UTF-8 in accepted envelope stream at line {line_number}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise IngestionAdapterError(
                f"invalid JSON in accepted envelope stream at line {line_number}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise IngestionAdapterError(
                f"accepted envelope at line {line_number} must be an object"
            )
        if expected_import_id is not None and envelope.get("import_id") != expected_import_id:
            raise IngestionAdapterError(
                f"accepted envelope import_id does not match CURRENT generation at line {line_number}"
            )
        yield observation_from_envelope(
            envelope,
            source_uri=source_uri,
            collected_at=collected_at,
            observed_at=observed_at,
            media_type=media_type,
            language=language,
        )



def export_current_generation(
    pointer_path: str | Path,
    output_path: str | Path,
    *,
    source_uri: str,
    collected_at: str,
    observed_at: str | None = None,
    media_type: str = "text/plain",
    language: str | None = None,
) -> int:
    """Atomically export validated observations as deterministic JSONL.

    The temporary file is created beside the destination and replaces it only
    after the entire accepted stream has converted successfully.
    """
    pointer = Path(pointer_path)
    manifest, generation = _verified_current_generation(pointer)
    accepted_path = generation / "accepted.jsonl"
    generation_dir = generation.resolve()
    destination = Path(output_path)
    if destination.is_symlink():
        raise IngestionAdapterError("export destination must not be a symlink")
    destination = destination.resolve()
    reserved = {
        pointer.resolve(),
        accepted_path.resolve(),
        (generation_dir / "quarantine.jsonl").resolve(),
    }
    if destination in reserved or destination.parent == generation_dir or generation_dir in destination.parents:
        raise IngestionAdapterError("export destination must be outside the current generation")
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary: Path | None = None
    count = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=destination.parent,
            prefix=".elite-observation-export-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            for observation in iter_current_generation(
                pointer,
                source_uri=source_uri,
                collected_at=collected_at,
                observed_at=observed_at,
                media_type=media_type,
                language=language,
            ):
                handle.write(json.dumps(
                    observation,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ))
                handle.write(chr(10))
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    return count
