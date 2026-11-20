# The landing page

A single static page, published to GitHub Pages by `.github/workflows/pages.yml`.
No framework, no external fonts, scripts or requests.

```bash
python3 site/build.py                                  # copy the figure in, then check
python3 -m http.server 8000 --directory site           # look at it on http://localhost:8000/
```

## What each file is

| File | What it is |
|---|---|
| `index.html` | the page: markup, CSS, and the script that plays the first screen and copies the command |
| `assets/icon.svg` | the tab icon |
| `assets/hero-data.json` | what the first screen plays (below) |
| `assets/open-billie-node-*.svg` | copied in by `build.py` from `docs/figures/`; not kept twice |
| `hero-data/make.py` | writes `assets/hero-data.json` |
| `hero-data/Cargo.toml`, `hero-data/src/main.rs` | the small program `make.py` uses to call the real translator |
| `captures/capture-validate.sh` | records `captures/validate.txt` |
| `captures/validate.txt` | the real kid validator on the example kid, shown on the page as it is |
| `build.py` | the check the pages workflow runs |

## The first screen

`hero-data/make.py` takes the conformance vector
`kids/examples/oetf/packages/oetf/shared/conformance/vectors/track_report_two_tracks.json`
(110 bytes, two tracks, synthetic), decodes and maps it with the example kid's own
Python decoder and mapper, and encodes each canonical track with the real Rust
translator in `runtime/rust/translator`, as CoT and as ASTERIX CAT062 with the
example source identifier SAC 1, SIC 2. The page highlights the frame's bytes field
by field (the labels follow `kids/examples/oetf/docs/WIRE_FORMAT.md`), then shows
the canonical record and the encoded output. With reduced motion it shows one still
state. SAPIENT, the third format, is left out because each SAPIENT message carries
a fresh report ID, so it differs on every run.

## Where each number comes from

`build.py` measures each one and fails when the page says something else. The page
marks each with `data-n`.

| Page says | `data-n` | Measured from |
|---|---|---|
| 110 B sensor frame | `frame-bytes` | `assets/hero-data.json`, `frameLength` |
| 2 tracks | `tracks` | the same file |
| 346 B CoT event for track 311 | `cot-bytes` | the same file, the translator's CoT output for the first track |
| CAT062: 31 B | `cat062-bytes` | the same file, its CAT062 output |
| 3 output formats | `formats` | variants of `pub enum EncoderFormat` in `runtime/rust/translator/src/request.rs` |
| 3 decoder runtimes | `runtimes` | `ls kids/examples/oetf/Containerfile*` |

`build.py` also fails if the code shown faintly behind the first screen is no
longer in `runtime/rust/translator/src/cot.rs`, or if the validator session on the
page differs from `captures/validate.txt`.
