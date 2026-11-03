# Contributing to Open Billie

Thanks for your interest in improving Open Billie. Contributions are made under the Apache License 2.0 as described in [LICENSE](LICENSE) and [INTENT.md](INTENT.md).

## Before you start

- Open an issue to discuss substantial changes before investing in implementation.
- Keep the platform sensor-neutral. Do not submit proprietary sensor protocols, decoder packages, captures, credentials, node identities, private endpoints, or deployment-specific data.
- Keep examples synthetic. Record provenance and license information for imported material.
- Do not add third-party source or generated artifacts unless their redistribution terms are clear and their notices are preserved.

## Development workflow

1. Fork the repository or create a feature branch.
2. Make a focused change with tests and documentation appropriate to its impact.
3. Run the relevant checks listed in [docs/TESTING.md](docs/TESTING.md). Include the commands and results in the pull request.
4. Submit a pull request describing the problem, implementation, compatibility impact, security implications, and validation performed.
5. Respond to review and CI feedback. Maintainers merge changes after review and passing required checks.

Do not include secrets or real operational data in issues, pull requests, logs, test fixtures, or screenshots. Do not report suspected vulnerabilities in public issues. Use GitHub private vulnerability reporting if enabled, or contact the repository maintainer directly.

## Developer Certificate of Origin

Open Billie uses a project-level DCO record modeled on Code.mil's lightweight approach. Before the first public release, maintainers with code contributions should add their own signed declaration to [CONTRIBUTORS.md](CONTRIBUTORS.md), after confirming they have the right to license the work they sign. Future code contributors add their own declaration before their code is accepted. This confirms that the contributor created the work or has the right to submit it under the project license. No DCO declaration is required for issue reports or documentation discussion.

The contributor record is public and retained with the repository history. Contributors should use a name and email address at which they can be contacted. Do not add a declaration on someone else's behalf.