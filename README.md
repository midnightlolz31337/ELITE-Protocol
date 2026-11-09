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
- `schemas/review-decision.schema.json` — review outcome.
- `docs/TRUST_MODEL.md` — trust boundaries and non-goals.

## Interoperability
Designed to interoperate with, not silently replace, [Huffman Protocol](https://github.com/HuffmanMainNode/Huffman-Protocol) and [Open Intelligence Exchange](https://github.com/HuffmanMainNode/Open-Intelligence-Exchange). Compatibility adapters are future work; no conformance is claimed yet.

Initial specification draft; not a certified standard or production security boundary.
