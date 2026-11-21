# Figures

`make-figures.py` draws every figure in this directory from the tree. Each
figure is written in a light and a dark variant for a `<picture>` element.

```sh
python3 -I docs/figures/make-figures.py           # write the SVG files
python3 -I docs/figures/make-figures.py --check   # exit 1 if a committed file is out of date
```

| Figure | Shows | Data |
|---|---|---|
| `open-billie-node` | the kid build and deploy steps; on a node, a kid package (listener, decoder, user mapping, conformance vectors) handing canonical records over the local Unix socket to the platform's Rust translator and encoder, local Zenoh, and the mTLS fabric client and bridge | `deploy/VERSION`; `kids/examples/oetf/billie-kid.yaml` (kid id, deployable decoder languages, listener transport and port, output formats); `schemas/canonical-track-v2.schema.json` (record version); `deploy/platform/templates/billie-translator.service.j2` (socket name); the `billie kid` verbs in `deploy/bin/billie` |

The script refuses to draw if a fact it shows is no longer in the tree.
Regenerate after any of those files change.

## Checks

The figure was rendered as an `<img>` at 830 px and 400 px wide in both
themes and inspected. Text is at least 13 units on an 880-unit canvas.
