# Contributing to Open Billie

Thanks for your interest in improving Open Billie. Portions written by U.S. Federal government employees within the scope of their employment are not subject to copyright in the U.S.; in countries where copyright is recognized, they and all other contributions are licensed under the [Apache License 2.0](LICENSE). See [INTENT.md](INTENT.md). Contributions are accepted under the [Policy](#policy) below.

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

**NOTE: This CONTRIBUTING.md is for software contributions. You do not need to follow the Developer's Certificate of Origin (DCO) process for commenting on this repository's documentation, such as CONTRIBUTING.md, INTENT.md, etc. or for submitting issues.**

## Policy

### 1. Introduction

The project maintainer for this Project will only accept contributions using the Developer's Certificate of Origin 1.1 located at [developercertificate.org](https://developercertificate.org) ("DCO"). The DCO is a legally binding statement asserting that you are the creator of your contribution, or that you otherwise have the authority to distribute the contribution, and that you are intentionally making the contribution available under the license associated with the Project ("License").

### 2. Developer Certificate of Origin Process

Before submitting contributing code to this repository for the first time, you'll need to sign a Developer Certificate of Origin (DCO) (see below). To agree to the DCO, add a `Signed-off-by` line to every commit with `git commit -s`. At a high level, signing off tells us that you have the right to submit the work you're contributing and indicates that you consent to our treating the contribution in a way consistent with the license associated with this software (as described in [LICENSE](LICENSE) and [INTENT.md](INTENT.md)) and its documentation ("Project").

### 3. Important Points

Pseudonymous or anonymous contributions are permissible, but you must be reachable at the email address provided in the Signed-off-by line.

If your contribution is significant, you are also welcome to add your name and copyright date to the source file header.

U.S. Federal law prevents the government from accepting gratuitous services unless certain conditions are met. By submitting a pull request, you acknowledge that your services are offered without expectation of payment and that you expressly waive any future pay claims against the U.S. Federal government related to your contribution.

If you are a U.S. Federal government employee and use a `*.mil` or `*.gov` email address, we interpret your Signed-off-by to mean that the contribution was created in whole or in part by you and that your contribution is not subject to copyright protections.

### 4. DCO Text

The full text of the DCO is included below and is available online at [developercertificate.org](https://developercertificate.org):

```txt
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.
1 Letterman Drive
Suite D4700
San Francisco, CA, 94129

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.

Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

[CONTRIBUTORS.md](CONTRIBUTORS.md) records the project-level declarations made before per-commit sign-off was adopted; no new entries are added there.
