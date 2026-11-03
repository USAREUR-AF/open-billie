# OETF example import record

## Source and disposition

- Source workspace: a separate working directory used to transfer the synthetic example into this repository. The directory name and lack of Git metadata do not identify an upstream author or establish a separate code origin.
- Source revision: unavailable; the supplied directory had no `.git` metadata when reviewed.
- Source declaration: the maintainer states that an AI agent created OETF in response to their instructions as a fictional example format; it is not modeled on a real radar interface and contains no proprietary sensor data. The separate working directory was a transfer location, not an upstream project.
- Package license metadata: the transfer copy's manifests declared ISC but supplied no corresponding license text. The maintainer directed that the example be released under this repository's Apache-2.0 terms, and the package metadata now matches. The initial ISC metadata is recorded as transfer metadata, not evidence of an ISC-licensed upstream source.
- License file: the source workspace had no license text. The maintainer confirms the example was generated for this project and authorizes its inclusion under the repository Apache-2.0 license. This records project provenance and maintainer intent; it does not replace any independent legal or organizational review required before public release.
- Destination: `kids/examples/oetf/`, explicitly a synthetic example kid and excluded from the core platform release allowlist.

## Imported components

- Normative wire format: `docs/WIRE_FORMAT.md`.
- Shared language-neutral schemas: `packages/oetf/shared/schemas/`.
- OETF-to-CAT-062, CoT, and SAPIENT maps: `packages/oetf/shared/mappings/`.
- Classification lookup tables: `packages/oetf/shared/lookups/`.
- Synthetic golden vectors: `packages/oetf/shared/conformance/vectors/`.
- TypeScript decoder, builder, and map path adapter with tests.
- Python decoder, builder, mapper, and conformance tests.
- Rust decoder, builder, mapper, embedded shared data, and conformance tests.
- Schema generator and TypeScript shared-data pack helper.
- Added an Open Billie-side Python TCP/UDP-to-translator-socket runtime and synthetic integration test around the imported components. Sensor packages do not publish directly to Zenoh or receive fabric credentials; the Open Billie platform owns that transport. The original OETF source workspace was not edited.

## Changes made during import

- Replaced the original private GitHub package names with local `@open-billie/*` workspace names.
- Removed GitHub Packages `publishConfig`, private repository URLs, and `.npmrc` scope configuration.
- Removed the vector-generation command that required a sibling Billie Modular translator checkout; the checked-in synthetic vectors remain the test baseline.
- Kept all OETF schemas, maps, and lookups under the example kid. The Open Billie platform builder does not include this directory.

## Verification

The imported JSON files are checked in their existing language-specific conformance suites. Open Billie verifies that the synthetic kid sends a decoded and canonically mapped record through the versioned translator socket. Open Billie platform acceptance must also cover local Zenoh routing, prefix forwarding, and mTLS before claiming connected end-to-end support.
