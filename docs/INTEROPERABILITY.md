# Interoperability roadmap

ELITE initially defines JSON envelopes and schemas only.

Existing systems to compare:
- Huffman Protocol: https://github.com/HuffmanMainNode/Huffman-Protocol
- Open Intelligence Exchange: https://github.com/HuffmanMainNode/Open-Intelligence-Exchange
- W3C PROV-O: https://www.w3.org/TR/prov-o/
- JSON Schema 2020-12: https://json-schema.org/draft/2020-12

An adapter must document source/target schema versions, lossy mappings, identifier and timestamp normalization, digest/signature semantics, unknown-field handling, and validation fixtures. Do not claim compatibility until fixtures pass against both sides. Never silently discard provenance, uncertainty, license, or authorization fields.
