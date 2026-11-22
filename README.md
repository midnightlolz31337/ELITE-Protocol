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
- `schemas/observation.schema.json` — normalized source observation.
- `schemas/claim.schema.json` — proposition with evidence references and uncertainty.
- `schemas/review-decision.schema.json` — versioned review outcome.
- `validator.py` — JSON Schema and bundle-level reference validation.
- `docs/TRUST_MODEL.md` — trust boundaries and non-goals.\n- `adapters/ingestion_v1.py` — versioned adapter from accepted Ingestion Core envelopes to Observation 1.1.0.\n- `docs/INGESTION_ADAPTER_V1.md` — conversion contract, digest scopes, and limitations.

## Validation
Install the runtime validation dependency and run the conformance suite:

```bash
python -m pip install --requirement requirements.txt
python -m unittest discover -s tests -v
```

The validator enforces JSON Schema Draft 2020-12, including date-time format checks. Observation schema version 1.1.0 requires an explicit integrity scope: `content.text.utf8`. The validator recomputes SHA-256 over the exact UTF-8 encoding of the decoded `content.text` value and rejects a mismatch. Bundle validation additionally requires unique observation, claim, and decision identifiers; each claim evidence reference must resolve to an observation in the supplied bundle; and each review subject must use `observation:<id>` or `claim:<id>` and resolve within that bundle.

Bundle validation is intentionally local to the supplied bundle and accepts at most 10,000 observations, 10,000 claims, and 10,000 review decisions per call. Claim evidence lists are limited to 256 references; observation limitations and claim uncertainty lists are limited to 128 entries each. The validator bounds iterable materialization and rejects non-object records. These are resource-safety ceilings, not throughput guarantees. The observation digest does not cover the original serialized JSON/CSV source bytes, media type, or other metadata; it covers only the decoded text field under the declared scope. It does not establish truth, source authenticity, legal authority, cryptographic signature validity, or external-store existence. Callers must provide the complete reference set they intend to validate.

## Interoperability
Designed to interoperate with, not silently replace, [Huffman Protocol](https://github.com/HuffmanMainNode/Huffman-Protocol) and [Open Intelligence Exchange](https://github.com/HuffmanMainNode/Open-Intelligence-Exchange). Compatibility adapters are future work; no conformance with those external protocols is claimed.

Initial specification draft; not a certified standard or production security boundary. The ingestion prototype currently emits its own import envelope; an explicit, versioned adapter is still required before treating ingestion output as an ELITE Observation.


## License

This project is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE). The project code is offered under Apache-2.0; this does not grant trademark rights.
