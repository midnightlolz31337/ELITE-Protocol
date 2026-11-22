"""Fail-closed adapter from ELITE Ingestion Core envelopes to Observation 1.1.0.

The adapter preserves the ingestion record digest separately from the
Observation content.text digest. It never promotes quarantined envelopes.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from validator import validate_document

SCHEMA_VERSION = "1.1.0"
SOURCE_DIGEST_SCOPES = {
    "jsonl": "ingestion.jsonl.line.bytes",
    "csv": "ingestion.csv.normalized_row.utf8",
}


class IngestionAdapterError(ValueError):
    """Raised when an ingestion envelope cannot be safely adapted."""


def observation_from_envelope(
    envelope: Mapping[str, Any],
    *,
    source_uri: str,
    collected_at: str,
    source_format: str,
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
    digest = envelope.get("content_sha256")
    size_bytes = envelope.get("raw_size_bytes")
    for name, value in (("source_id", source_id), ("import_id", import_id), ("record_id", record_id)):
        if not isinstance(value, str) or not value.strip():
            raise IngestionAdapterError(f"missing or invalid {name}")
    if isinstance(source_line, bool) or not isinstance(source_line, int) or source_line < 1:
        raise IngestionAdapterError("source_record must be a positive line number")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise IngestionAdapterError("content_sha256 must be a lowercase SHA-256 hex digest")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise IngestionAdapterError("raw_size_bytes must be a non-negative integer")
    if source_format not in SOURCE_DIGEST_SCOPES:
        raise IngestionAdapterError("source_format must be jsonl or csv")
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
            "CSV digest covers the ingestion core's normalized row representation, not original source-file or physical-row bytes."
        )
    else:
        limitations.append(
            "JSONL digest covers the exact input line bytes read by ingestion, including its line terminator when present; it is not a whole-file digest."
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


def iter_accepted_jsonl(
    path: str | Path,
    *,
    source_uri: str,
    collected_at: str,
    source_format: str,
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
                source_format=source_format,
                observed_at=observed_at,
                media_type=media_type,
                language=language,
            )
