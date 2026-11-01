# OETF example import record

## Source and disposition

- Source workspace: `billie-decoder-oetf`, supplied in the shared local Projects directory.
- Source revision: unavailable; the supplied directory had no `.git` metadata when reviewed.
- Source declaration: the OETF README and wire-format specification describe OETF as a made-up format that is not modeled on any real radar interface.
- Package license metadata: ISC in the source root and language package manifests.
- License file: none was present in the source workspace. The imported files remain local project material; confirm the copyright holder and add the required ISC notice before public redistribution.
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
