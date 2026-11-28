# Releasing Open Billie

A release is a tag `v<version>` on a commit on `main`, where `<version>` is `deploy/VERSION`. The tag runs [`.github/workflows/release.yml`](.github/workflows/release.yml), which builds, signs and publishes it. Nobody builds or signs a release by hand, and no long-lived signing key exists.

## What a release holds

For each of amd64 and arm64, built natively on Ubuntu 24.04:

| File | What it is |
|---|---|
| `billie-platform_<version>-<rev>_<arch>.deb` | the platform package; its own `Version` is `<version>+<rev>` |
| `billie-platform-<version>-<rev>_<arch>.tar.gz` | the same release tree as a tarball |
| `SHA256SUMS-<arch>` | the `.deb` and the tarball, as `tools/install-to-node.sh` checks them |
| `billie-kid-weather-station-bite_<kid version>_<arch>.tar.gz` and its `.sha256` | the synthetic test kid's bundle, built with `billie kid build`; `billie kid install` reads the sidecar |
| `billie-kid-weather-station-bite_<kid version>_<arch>.spdx.json` | an SPDX SBOM of the kid image in that bundle, by its OCI digest (`tools/generate_kid_sbom.py`) |
| `billie-platform_<version>-<rev>_<arch>.crates.spdx.json` | an SPDX SBOM of the crates in `runtime/rust/Cargo.lock`, from which the translator is built |

And once:

| File | What it is |
|---|---|
| `SHA256SUMS` | the SHA-256 of every file above |
| `SHA256SUMS.sigstore.json` | its keyless cosign signature: a Sigstore bundle v0.3 in the public Rekor v1 log, whose certificate names this repository's `release.yml` at the tag |
| `<file>.sigstore.json` for each `.deb`, platform tarball and `SHA256SUMS-<arch>` | the per-file signatures `tools/install-to-node.sh` checks |

File names use `-` where the package version has `+`, because GitHub may rename a release file whose name holds `+`. The workflow publishes the release only after it checks that GitHub's asset names are the names in `SHA256SUMS`.

## Checking a release

```sh
cosign verify-blob SHA256SUMS --bundle SHA256SUMS.sigstore.json \
  --certificate-identity "https://github.com/USAREUR-AF/open-billie/.github/workflows/release.yml@refs/tags/v<version>" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
sha256sum --check --ignore-missing SHA256SUMS
```

`tools/install-to-node.sh` takes the same identity with `--certificate-identity` and checks the per-file signatures itself.

## Cutting a release

1. On a branch, set `deploy/VERSION`, and give `CHANGELOG.md` a dated section, `## [<version>] - YYYY-MM-DD`. The release notes are that section. Merge it.
2. Run the workflow by hand on `main` (*Actions*, *Signed platform release*, *Run workflow*). This is a dry run: it builds, signs and checks everything, keeps the files as the `signed` workflow artifact and publishes nothing. Check the file list and read the SBOMs (`docs/SBOM_REVIEW.md`).
3. Tag that commit and push the tag:
   ```sh
   git tag -s v<version> -m "Open Billie <version>" <commit>
   git push origin v<version>
   ```
   The workflow refuses a tag that is not on `main`, does not match `deploy/VERSION`, or has no dated changelog section.

A fix to a published release is a new version. A tag is never moved.
