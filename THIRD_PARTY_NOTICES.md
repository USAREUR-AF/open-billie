# Third-party notices

The repository's Apache-2.0 license applies to Open Billie-authored material only. It does not replace the licenses of third-party dependencies, base images, operating-system packages, standards, or separately identified works.

See the [third-party software inventory](docs/THIRD_PARTY_INVENTORY.md) for the reviewed source manifests, lockfiles, declared dependencies, container images, and outstanding artifact-level work. It is a source-level inventory, not a complete SBOM for a generated image or release artifact.

## Derived code

The OETF example's TypeScript decoder (`parser.ts`, `decoder.ts`, `index.ts`) and `kids/examples/oetf/tsconfig.base.json` are adapted from the Billie Modular project, Copyright (c) 2026 DesertGOAT, ISC License. The ISC permission notice and the file list are in [NOTICE](NOTICE); the OETF TypeScript runtime image carries the same file at `/licenses/NOTICE`.

## Standards references and implementation provenance

- **SAPIENT / BSI Flex 335 v2.0:** The translator contains Open Billie-authored protobuf serialization code. Its test-only Prost model mirrors the SAPIENT v2 message field layout published by [Dstl's SAPIENT-Proto-Files](https://github.com/dstl/SAPIENT-Proto-Files/tree/main/bsi_flex_335_v2_0). Dstl's [repository licence](https://github.com/dstl/SAPIENT-Proto-Files/blob/main/LICENCE.txt) identifies Crown-owned copyright 2023 and licenses the protobuf files under Apache-2.0, except where otherwise noted. Open Billie does not include those `.proto` files. The BSI Flex standard document is separately copyright BSI ([BSI product description](https://groupsiteppdmig.bsigroup.com/en-GB/insights-and-media/insights/brochures/bsi-flex-335-interface-of-the-sapient-sensor-management-specification/)); Open Billie does not include or reproduce its text.
- **ASTERIX CAT062:** The translator implements a documented subset of EUROCONTROL SPEC-0149-9, Edition 1.21. The [official specification](https://www.eurocontrol.int/sites/default/files/2025-06/asterix-cat062-system-track-data-p9-ed1-21.pdf) is identified as a released issue intended for general public use. Open Billie does not include the specification text.
- **Cursor on Target:** The translator implements the project's documented CoT profile. The governing [MIL-STD-6090 record](https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=284928) is maintained by DLA ASSIST. Open Billie does not include the standard document.

Before redistributing a built image or other artifact, inspect its final contents, generate an SBOM for each architecture and digest, and include any required third-party license texts and notices. Do not infer artifact notices from the repository license or a source lockfile alone.

## Notices verified in the OETF 0.2.0 Python candidate image

The Python candidate image contains pip 25.0.1. Its vendored dependency manifest pins `distlib==0.3.9`; distlib's package license is the Python Software Foundation License 2.0 (PSF-2.0). The image includes the Python runtime's `LICENSE.txt`, which contains the PSF license text. Verify that this file is retained when rebuilding or changing the Python base image. See the [distlib 0.3.9 license metadata](https://pypi.org/project/distlib/0.3.9/) and [pip 25.0.1 vendored dependency list](https://github.com/pypa/pip/blob/25.0.1/src/pip/_vendor/vendor.txt).

The six Windows launcher executables under `pip/_vendor/distlib/` are separately covered by the notice at the end of the tagged [distlib 0.3.9 launcher source](https://github.com/pypa/distlib/blob/0.3.9/PC/launcher.c). The source notice is copyright Vinay Sajip and permits source and binary redistribution under these conditions:

```text
Copyright (C) 2011-2022 Vinay Sajip. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
```

## Node.js notice for the OETF TypeScript image

The OETF TypeScript runtime uses Node.js 22.14.0. The exact upstream [`v22.14.0/LICENSE`](https://github.com/nodejs/node/blob/v22.14.0/LICENSE) is stored at `kids/examples/oetf/licenses/node-v22.14.0-LICENSE` and copied into the runtime image at `/licenses/node-v22.14.0-LICENSE`. It includes Node.js licensing and bundled third-party notices. Its SHA-256 is `1474fea5eff88dc92763acca3ca1f54b51fa153be1529eae74ace35957aea9ce`. The rebuilt arm64 TypeScript candidate image contains this exact file; its SBOM is recorded in [SBOM_REVIEW.md](docs/SBOM_REVIEW.md). The candidate is unsigned and not a release artifact.

The Debian base-image package copyright files remain in the candidate OCI images under `/usr/share/doc/*/copyright`. Their package-level mapping and the exact release identity for the pinned Zenoh image are not yet fully reviewed; see [SBOM_REVIEW.md](docs/SBOM_REVIEW.md).
