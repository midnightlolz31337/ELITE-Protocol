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
- `docs/TRUST_MODEL.md` — trust boundaries and non-goals.

## Validation
Install the runtime validation dependency and run the conformance suite:

```bash
python -m pip install --requirement requirements.txt
python -m unittest discover -s tests -v
```

The validator enforces JSON Schema Draft 2020-12, including date-time format checks. Bundle validation additionally requires unique observation, claim, and decision identifiers; each claim evidence reference must resolve to an observation in the supplied bundle; and each review subject must use `observation:<id>` or `claim:<id>` and resolve within that bundle.

Bundle validation is intentionally local to the supplied bundle. It does not establish truth, source authenticity, legal authority, cryptographic signature validity, or external-store existence. Callers must provide the complete reference set they intend to validate.

## Interoperability
Designed to interoperate with, not silently replace, [Huffman Protocol](https://github.com/HuffmanMainNode/Huffman-Protocol) and [Open Intelligence Exchange](https://github.com/HuffmanMainNode/Open-Intelligence-Exchange). Compatibility adapters are future work; no conformance with those external protocols is claimed.

Initial specification draft; not a certified standard or production security boundary.
