# Security policy

Open Billie provisions sensor nodes and bridges their data onto a fabric over mTLS. Security reports are prioritised over feature work.

## Reporting a vulnerability

**Do not open a public issue or pull request to report a vulnerability.**

**[Report a vulnerability privately](https://github.com/USAREUR-AF/open-billie/security/advisories/new)**

You can also open the reporting form from this repository's *Security* tab by selecting *Report a vulnerability*.

Reports are private and accessible to repository administrators, organization owners, security managers, the reporter, and collaborators explicitly added to the advisory. Being listed in `CODEOWNERS` does not itself grant access. Reports remain private until an authorized maintainer publishes the advisory. See [GitHub's advisory permissions](https://docs.github.com/en/code-security/reference/permissions/repository-security-advisory) for details.

Include a description of the issue and its impact, reproduction steps or a proof of concept, the affected versions or commits, and whether you have shared it elsewhere. Do not include credentials, private keys, real sensor captures, personal data or operational network details; the maintainers will arrange a secure transfer if one is needed.

## What to expect

| Step | Target |
|---|---|
| Acknowledgement | 3 working days |
| Triage and severity | 7 working days |
| Fix or mitigation for a confirmed high or critical issue | 30 days, with a coordinated disclosure date agreed with you |
| Public advisory | when the fix is released, crediting you unless you prefer otherwise |

## Scope

In scope: the Open Billie platform, its provisioning and kid-management tools, the shared translator, the synthetic OETF example, and the images and release artifacts built from this repository. Out of scope: the upstream projects it assembles (Zenoh, NetBird, Podman, Ansible); report those to their maintainers, and tell us too if Open Billie's integration is affected.

## Supported versions

Pre-1.0, the latest tagged release is supported. Fixes land on `main` and are released by tag.
