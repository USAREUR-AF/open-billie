# OETF example import record

## Source and disposition

- Source workspace: a separate working directory used to transfer the synthetic example into this repository; it carried no `.git` metadata.
- Source revision: Billie Modular `3909b655b1ca2a3bd55406120f0ef471658a6e68` for the TypeScript decoder files and `45ce20b7ec4ca5996bcbed20059fb0445eb9bf7f` for `tsconfig.base.json`; the transfer directory itself carried no `.git` metadata.
- Code origin: the TypeScript decoder code was adapted from the Billie Modular `packages/rps42/decoder` package (revision `3909b655b1ca2a3bd55406120f0ef471658a6e68`): `parser.ts` is the schema-driven byte reader with its byte order changed, `decoder.ts` keeps the streaming structure with new framing (magic, length, CRC-16) and `index.ts` keeps the export shape. `tsconfig.base.json` is the Billie Modular workspace file (revision `45ce20b7ec4ca5996bcbed20059fb0445eb9bf7f`). The OETF wire format, schemas, mappings, lookups, conformance vectors and the Python and Rust implementations were written for this project and do not derive from the RPS-42 package or any real sensor interface; the field layouts, message identifiers, byte order and framing differ from RPS-42.
- Source declaration: the maintainer states that OETF is a fictional example format created for this project with AI assistance; it is not modeled on a real radar interface and contains no proprietary sensor data.
- Package license metadata: the transfer copy's manifests declared ISC, copied from Billie Modular's repository license. The package metadata now states Apache-2.0, the repository license.
- License file: the source workspace had no license text. Billie Modular's repository carried an ISC License naming DesertGOAT as the copyright holder. Billie Modular was written entirely by U.S. Federal government employees, so that notice did not reflect its authorship; the derived files are covered by the same terms as the rest of Open Billie (see `INTENT.md`). `NOTICE` and `kids/examples/oetf/licenses/NOTICE` list the derived files and their source revisions.
- Authority: the maintainer authorizes inclusion under these terms. This records project provenance and maintainer intent; it does not replace any independent legal or organizational review required before public release.
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
