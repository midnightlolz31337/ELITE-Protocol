"""Fail-closed adapter from ELITE Ingestion Core envelopes to Observation 1.1.0.

The adapter preserves the ingestion record digest separately from the
Observation content.text digest. It never promotes quarantined envelopes.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from validator import validate_document

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
    if source_format not in SOURCE_DIGEST_SCOPES:
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
            raise IngestionAdapterError(f"duplicate JSON key in CURRENT.json: {key}")
        result[key] = value
    return result


def accepted_jsonl_from_current(pointer_path: str | Path) -> Path:
    """Resolve accepted.jsonl only after verifying the ingestion CURRENT pointer."""
    pointer = Path(pointer_path)
    if pointer.is_symlink():
        raise IngestionAdapterError("CURRENT.json must not be a symlink")
    try:
        manifest = json.loads(pointer.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionAdapterError(f"cannot read CURRENT.json: {exc}") from exc
    expected_keys = {
        "schema_version", "generation_id", "generation_path", "created_at",
        "accepted_count", "quarantine_count", "files",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise IngestionAdapterError("CURRENT.json has an invalid structure")
    if manifest["schema_version"] != "1":
        raise IngestionAdapterError("unsupported CURRENT.json schema version")
    created_at = manifest["created_at"]
    if not isinstance(created_at, str) or not created_at:
        raise IngestionAdapterError("CURRENT.json created_at is invalid")
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IngestionAdapterError("CURRENT.json created_at is not a valid ISO 8601 timestamp") from exc
    if parsed_created_at.tzinfo is None or parsed_created_at.utcoffset() is None:
        raise IngestionAdapterError("CURRENT.json created_at must include a timezone")
    generation_id = manifest["generation_id"]
    if not isinstance(generation_id, str):
        raise IngestionAdapterError("CURRENT.json generation_id is invalid")
    try:
        parsed_id = uuid.UUID(generation_id)
    except ValueError as exc:
        raise IngestionAdapterError("CURRENT.json generation_id is not a UUID") from exc
    if str(parsed_id) != generation_id:
        raise IngestionAdapterError("CURRENT.json generation_id is not canonical")
    relative_generation = f"generations/{generation_id}"
    if manifest["generation_path"] != relative_generation:
        raise IngestionAdapterError("CURRENT.json generation path is invalid")
    for key in ("accepted_count", "quarantine_count"):
        value = manifest[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise IngestionAdapterError(f"CURRENT.json {key} is invalid")
    root = pointer.parent.resolve()
    generations = root / "generations"
    generation = root / relative_generation
    if generations.is_symlink() or generation.is_symlink():
        raise IngestionAdapterError("current generation path must not contain symlinks")
    resolved_generations = generations.resolve()
    resolved_generation = generation.resolve()
    if resolved_generation.parent != resolved_generations or not resolved_generation.is_dir():
        raise IngestionAdapterError("current generation is missing or outside generations/")
    files = manifest["files"]
    names = ("accepted.jsonl", "quarantine.jsonl")
    if not isinstance(files, dict) or set(files) != set(names):
        raise IngestionAdapterError("CURRENT.json file map is invalid")
    for name in names:
        entry = files[name]
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise IngestionAdapterError(f"CURRENT.json entry for {name} is invalid")
        if entry["path"] != f"{relative_generation}/{name}":
            raise IngestionAdapterError(f"CURRENT.json path for {name} is invalid")
        file_path = resolved_generation / name
        if file_path.is_symlink() or not file_path.is_file():
            raise IngestionAdapterError(f"current generation file is missing or unsafe: {name}")
        size, digest = entry["size"], entry["sha256"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise IngestionAdapterError(f"CURRENT.json size for {name} is invalid")
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise IngestionAdapterError(f"CURRENT.json SHA-256 for {name} is invalid")
        actual_hash = hashlib.sha256()
        actual_count = 0
        last_byte = None
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                actual_hash.update(chunk)
                actual_count += chunk.count(bytes([10]))
                if chunk:
                    last_byte = chunk[-1]
        if file_path.stat().st_size != size or actual_hash.hexdigest() != digest:
            raise IngestionAdapterError(f"current generation integrity check failed: {name}")
        if size and last_byte != 10:
            raise IngestionAdapterError(f"current generation file is not newline-terminated: {name}")
        expected_count = manifest["accepted_count" if name == "accepted.jsonl" else "quarantine_count"]
        if actual_count != expected_count:
            raise IngestionAdapterError(f"current generation record count mismatch: {name}")
    return resolved_generation / "accepted.jsonl"


def iter_current_generation(pointer_path: str | Path, **adapter_options: Any) -> Iterator[dict[str, Any]]:
    """Stream observations from the verified generation named by CURRENT.json."""
    accepted_path = accepted_jsonl_from_current(pointer_path)
    yield from iter_accepted_jsonl(accepted_path, **adapter_options)


def iter_accepted_jsonl(
    path: str | Path,
    *,
    source_uri: str,
    collected_at: str,
    observed_at: str | None = None,
    media_type: str = "text/plain",
    language: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream an accepted.jsonl generation file; malformed lines fail closed."""
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise IngestionAdapterError(f"blank line in accepted envelope stream at line {line_number}")
            try:
                envelope = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IngestionAdapterError(
                    f"invalid JSON in accepted envelope stream at line {line_number}"
                ) from exc
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
    accepted_path = accepted_jsonl_from_current(pointer)
    generation_dir = accepted_path.parent.resolve()
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
            for observation in iter_accepted_jsonl(
                accepted_path,
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
