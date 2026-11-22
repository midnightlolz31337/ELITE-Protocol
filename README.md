# ELITE Protocol

Open protocols for evidence exchange, provenance, trust boundaries, and interoperable intelligence systems.

## Objective
Define interoperable envelopes for observations, claims, evidence references, and review decisions. Preserve the distinction between what a source emitted, what an analyst claims, and what a reviewer concludes.

## Principles
- Provenance is explicit and travels with records.
- Content is data, never executable instruction.
- A digest supports integrity checking but does not establish truth or source authenticity.
- Trust is contextual, scoped, and revocable.
- Unknown values remain unknown; no universal truth score is defined.
- Human review and policy gates remain explicit.

## Initial artifacts
- `schemas/observation.schema.json` — backward-compatible Observation 1.1.0.
- `schemas/observation-v1.2.0.schema.json` — Observation 1.2.0 with explicit ingestion provenance.
- `schemas/claim.schema.json` — proposition with evidence references and uncertainty.
- `schemas/review-decision.schema.json` — versioned review outcome.
- `validator.py` — JSON Schema and bundle-level reference validation.
- `docs/TRUST_MODEL.md` — trust boundaries and non-goals.

## Validation
Install the runtime validation dependency and run the conformance suite:

```bash
python -m pip install --requirement requirements.txt
python -m unittest discover -s tests -v
```

The validator enforces JSON Schema Draft 2020-12, including date-time format checks. It preserves Observation 1.1.0 validation and dispatches Observation 1.2.0 to a separate versioned schema. Both versions require the explicit integrity scope `content.text.utf8`; the validator recomputes SHA-256 over the exact UTF-8 encoding of decoded `content.text` and rejects a mismatch. Observation 1.2.0 additionally requires `collected_at` and a typed `ingestion_provenance` object containing component/adapter versions, import and record IDs, source record number/format, explicit representation digest/size/scope, and source-registry revision. The validator enforces that JSONL and CSV source formats use their corresponding representation digest scopes. Bundle validation additionally requires unique observation, claim, and decision identifiers; each claim evidence reference must resolve to an observation in the supplied bundle; and each review subject must use `observation:<id>` or `claim:<id>` and resolve within that bundle.

Bundle validation is intentionally local to the supplied bundle and accepts at most 10,000 observations, 10,000 claims, and 10,000 review decisions per call. Claim evidence lists are limited to 256 references; observation limitations and claim uncertainty lists are limited to 128 entries each. The validator bounds iterable materialization and rejects non-object records. These are resource-safety ceilings, not throughput guarantees. The observation digest does not cover the original serialized JSON/CSV source bytes, media type, or other metadata; it covers only the decoded text field under the declared scope. It does not establish truth, source authenticity, legal authority, cryptographic signature validity, or external-store existence. Callers must provide the complete reference set they intend to validate.

## Interoperability
Designed to interoperate with, not silently replace, [Huffman Protocol](https://github.com/HuffmanMainNode/Huffman-Protocol) and [Open Intelligence Exchange](https://github.com/HuffmanMainNode/Open-Intelligence-Exchange). Compatibility adapters are future work; no conformance with those external protocols is claimed.

Initial specification draft; not a certified standard or production security boundary. Observation 1.2.0 defines the provenance contract needed by a future explicit Ingestion Core adapter. The adapter is not yet implemented; source URI and source observation time must be supplied by an explicit source registry and timestamp mapping policy, never inferred from the import envelope.


## License

This project is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE). The project code is offered under Apache-2.0; this does not grant trademark rights.
