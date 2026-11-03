# Contributing to Open Billie

Thanks for your interest in improving Open Billie. Contributions are made under the Apache License 2.0 as described in [LICENSE](LICENSE) and [INTENT.md](INTENT.md).

## Before you start

- Open an issue to discuss substantial changes before investing in implementation.
- Keep the platform sensor-neutral. Do not submit proprietary sensor protocols, decoder packages, captures, credentials, node identities, private endpoints, or deployment-specific data.
- Keep examples synthetic. Record provenance and license information for imported material.
- Do not add third-party source or generated artifacts unless their redistribution terms are clear and their notices are preserved.

## Development workflow

1. Fork the repository, or branch from `main` if you have write access.
2. Make a focused change with tests and documentation appropriate to its impact.
3. Run the relevant checks listed in [docs/TESTING.md](docs/TESTING.md). Include the commands and results in the pull request.
4. Commit with a DCO sign-off: `git commit -s -m "..."`. Signed commits (SSH or GPG) are required on `main`; set up [commit signing](https://docs.github.com/en/authentication/managing-commit-signature-verification) once.
5. Open a pull request against `main` describing the problem, implementation, compatibility impact, security implications, and validation performed. One approving review from a code owner merges it, by squash, after the required checks pass.

Do not include secrets or real operational data in issues, pull requests, logs, test fixtures, or screenshots. Do not report suspected vulnerabilities in public issues. Use GitHub private vulnerability reporting if enabled, or contact the repository maintainer directly.

## Developer Certificate of Origin

Every commit carries a sign-off (`git commit -s`). By signing off you certify the [Developer Certificate of Origin 1.1](https://developercertificate.org/): you wrote the change or have the right to submit it under this project's license. There is no contributor license agreement. [CONTRIBUTORS.md](CONTRIBUTORS.md) records the declarations made before per-commit sign-off was adopted. No sign-off is needed for issue reports or discussion.