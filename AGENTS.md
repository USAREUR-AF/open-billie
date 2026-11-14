# AGENTS.md

Instructions for AI coding agents, and a short version for anyone working here. [CONTRIBUTING.md](CONTRIBUTING.md) is the full process.

## What this repository is

Open Billie prepares a node, builds sensor-specific packages (called kids), and publishes normalized sensor data through a shared Rust translator and Zenoh. A kid holds a sensor decoder, a schema, a mapping and conformance vectors. The platform is sensor-neutral: the example package and the sensor simulator in this repository use synthetic data.

## Layout

| Path | What |
|---|---|
| `deploy/` | the `billie` command (`deploy/bin/billie`), the Ansible playbooks (`deploy/platform/`), the provisioning guide |
| `runtime/rust/` | the translator workspace |
| `kids/_template/`, `kids/examples/oetf/` | the kid package template and the synthetic example, in Python, Rust and TypeScript |
| `tools/` | setup, build and deploy scripts, the release and boundary checks, and the platform unit tests (`test_*.py`) |
| `schemas/` | schemas |
| `docs/` | guides, architecture, and `TESTING.md` |

## Before you push

CI (`.github/workflows/ci.yml`) runs these:

```bash
python -m pip install --requirement requirements-ci.txt
python -m unittest discover --start-directory tools --pattern 'test_*.py' --verbose
python -m compileall -q deploy/bin tools
python tools/check_release_hygiene.py
python tools/check_public_boundary.py
cargo fmt --manifest-path runtime/rust/Cargo.toml --all -- --check
cargo test --locked --workspace --manifest-path runtime/rust/Cargo.toml
```

For a change under `kids/examples/oetf/`, the workflow also runs that package's Python, Rust and TypeScript tests; copy the commands from it. Include the commands that you ran and their results in the pull request.

## Rules

1. **Sensor-neutral and synthetic.** No proprietary sensor protocol, decoder, capture, credential, node identity, private endpoint or deployment-specific data. `tools/check_public_boundary.py` scans the tracked source in CI.
2. **Commits.** Every commit is signed off (`git commit -s`, the DCO) and signed with a key GitHub verifies.
3. **Third-party material** is added only when its redistribution terms are clear and its notices are kept.
4. **Vulnerabilities** go through [SECURITY.md](SECURITY.md), never a public issue.

Open Billie publishes to a goat data fabric. The contribution guide for goat is [goatcore CONTRIBUTING.md](https://github.com/USAREUR-AF/goatcore/blob/main/CONTRIBUTING.md); this repository's own [CONTRIBUTING.md](CONTRIBUTING.md) is the one that applies here.
