# ELITE Ingestion Core → Protocol adapter v1

## Status

Experimental interoperability adapter. It targets the ELITE Observation schema 1.1.0 on the schema-conformance branch. It is not a certified standard or a source-authentication mechanism.

## Conversion contract

The adapter reads the Ingestion Core `accepted.jsonl` output as a stream and emits one validated ELITE Observation 1.1.0 per accepted envelope. It fails closed on malformed lines, non-accepted decisions, missing provenance, unsupported content shapes, invalid digests, or incomplete timestamps. Quarantine files are not accepted as input.

The caller must supply:
- the source URI (the ingestion envelope contains a source ID, not a canonical URI);
- the collection timestamp; and
- an observed-at timestamp when the source record does not contain an explicit one.

The source format is recorded by Ingestion Core in each envelope. The adapter derives the digest scope from that field and does not accept a caller override.

No timestamp, URI, publisher, license, or authorization is fabricated. The source URI is attribution metadata, not proof of ownership or authenticity.

## Two independent digest scopes

1. `integrity.scope=content.text.utf8`: SHA-256 recomputed by the adapter over the exact UTF-8 bytes of the decoded Observation `content.text`. The Protocol validator recomputes this digest.
2. `ingestion.record_digest`: the digest and byte count carried by the ingestion envelope, with an explicit source-format scope:
   - `ingestion.jsonl.line.bytes`: exact JSONL input line bytes consumed by Ingestion Core, including the line terminator when present;
   - `ingestion.csv.normalized_row.utf8`: normalized JSON serialization of the parsed CSV row, not original CSV file or physical-row bytes.

The two digests are not interchangeable. Neither proves source authenticity, legal authority, authorship, time, or truth.

## Provenance retained

The Observation retains source ID and caller-supplied URI, observation and collection timestamps, import ID, record ID, source line number, ingestion digest/scope/size, media type, content text, and content digest. The record ID is reused as the Observation ID to preserve a stable link to the originating ingestion envelope.

## Explicit non-goals

- Does not ingest quarantine output.
- Does not reconstruct original CSV bytes.
- Does not authenticate sources or operators, verify signatures, establish legal rights, or enforce source policy.
- Does not infer publisher, license, language, or observation time.
- Does not turn content into claims or assessments.
- Does not establish truth or certify either component for production use.

## Example

```python
from adapters.ingestion_v1 import iter_current_generation

for observation in iter_current_generation(
    "output/CURRENT.json",
    source_uri="https://example.org/source",
    collected_at="2026-11-22T12:30:00Z",
    observed_at="2026-11-22T12:00:00Z",
):
    print(observation)
```

The adapter verifies the `CURRENT.json` manifest, both generation files, their sizes, SHA-256 digests, newline termination, and manifest record counts, and rejects symlinked paths before reading the accepted stream.


## Cross-repository verification

Protocol CI checks out ELITE Ingestion Core PR #2 at the exact reviewed source revision `e7ff07339a3b5256cca0e983f03ccc579b6cfdeb`. The adapter test suite invokes its real CLI to create a committed generation from synthetic JSONL and CSV inputs, then resolves the resulting `CURRENT.json` through the adapter.

The JSONL integration test verifies the ingestion digest against exact source line bytes. The CSV integration test verifies the digest against the normalized row representation emitted by Ingestion Core and explicitly checks that it is not mislabeled as the original CSV file digest. This is a pinned cross-repository integration fixture, not a moving dependency on the default branch.
