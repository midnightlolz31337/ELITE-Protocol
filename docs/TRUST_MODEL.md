# ELITE trust model

## Trust is not a scalar
ELITE does not assign a universal trust or truth score to a source, observation, claim, person, or organization. Confidence is contextual and must be explained with evidence, limitations, and provenance.

## Distinctions
- **Source**: origin or publisher from which material is attributed.
- **Observation**: what was captured or received, with time and integrity metadata.
- **Claim**: a proposition asserted about the world.
- **Evidence reference**: pointer to observations relevant to a claim.
- **Assessment**: review outcome with rationale, reviewer type, and time.
- **Decision**: scoped operational choice such as accept, reject, quarantine, or request more evidence.

## Integrity, authenticity, truth
A matching digest indicates bytes match a previously recorded digest. It does not prove who created them, when they existed, whether the source was authorized, or whether the content is accurate. Signatures and trusted timestamps add evidence about origin and time but do not prove truth.

## Untrusted content
Source text, metadata, tool output, and agent-generated content are data. They must not override policy, trigger execution, or bypass human approval. Injection detection is defense in depth, not a guarantee.

## Human review
High-impact decisions, source authorization, disputed identity matches, and consequential claims require accountable human review. Automation may prioritize, normalize, flag, or explain; it must not disguise uncertainty.
