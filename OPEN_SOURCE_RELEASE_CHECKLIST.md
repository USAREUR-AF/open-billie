# Open source release checklist

This is the maintainer's short list for preparing Open Billie for outside contributions and public release. The detailed source dependency review is in [docs/THIRD_PARTY_INVENTORY.md](docs/THIRD_PARTY_INVENTORY.md).

## Maintainer actions

- [ ] Leave the current copyright line unchanged for the designated external reviewer. Record that review before a public distribution or tagged release; do not claim rights belonging to a contractor, employer, or other party without authorization.
- [ ] Add a reachable private conduct-report contact route to the repository profile and link it from `CODE_OF_CONDUCT.md` before accepting public contributions.
- [x] Add your own DCO entry in `CONTRIBUTORS.md` using your preferred public name and a reachable email. The entry is public and retained in Git history; no one should add it on your behalf. The declaration records your attestation that you have the rights described above; maintainers cannot independently establish that authority from the entry alone. This follows Code.mil's one-time project-level declaration approach rather than per-commit sign-offs.
- [x] Review the source dependency summary in `docs/THIRD_PARTY_INVENTORY.md`, including OETF provenance and the standards-reference/copying boundaries. Artifact dependency and license-text review remains required for any distributed build.
- [ ] Before distributing a platform or kid artifact, generate and review an SBOM and required license notices for each exact image digest and architecture. `python3 tools/generate_kid_sbom.py <kid-bundle.tar.gz>` now generates SPDX JSON from the bundled image after validating both checksums. Source lockfiles alone do not describe the complete OS/base-image contents.
- [x] Use a multi-stage TypeScript OETF image build so build/test dependencies are excluded from the runtime image.
- [ ] Decide whether historical deployment-specific identifiers in already-published Git history need any action before creating a tagged release. A local reachable-history scan passed on 2026-11-03; verify the public repository's branches and tags before making any decision about published history. If rewriting is needed, coordinate it with anyone who has cloned the public repository.
- [ ] Review the first public release contents and confirm no credentials, real sensor captures, proprietary protocols, or deployment secrets are included.

## Already added to the source tree

- Apache-2.0 project license and project intent.
- Contribution guidance and the maintainer's DCO declaration.
- OETF package metadata aligned with Apache-2.0 and a provenance note explaining its fictional synthetic origin.
- Third-party notice summary and source-level dependency inventory.

## Release decision

The maintainer DCO entry and source-level licensing documents are present. Confirm the copyright holder and authority to release every project-authored contribution. Artifact SBOM and notice review remains required before distributing built artifacts; it is separate from submitting the source repository.
