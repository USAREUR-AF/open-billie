# ADR 0001: goat-transformers is the only decoder, mapper and encoder; the native encoders are retired and a kid selects packs

Status: Proposed (2026-11-27)

## TL;DR (for a layperson)

An Open Billie node turns a sensor's messages into standard formats such as
CoT and ASTERIX CAT062. Today the translator holds two ways to write each
format: its own Rust encoder, and the
[goat-transformers](https://github.com/USAREUR-AF/goat-transformers) library,
which states a format as a data file called a pack. Each kid also carries its
own schema, mapping files and mapper code. This record makes the library the
only place a format is decoded, mapped or encoded. The translator's own
encoders are removed once the library writes the same output, and a kid
becomes a source of bytes plus a choice of packs.

## Context

The translator (`runtime/rust/translator`) has encoded through the library by
default for CoT and CAT062 since #35, and keeps its own encoder for each
format one environment variable away
(`docs/architecture/GOAT_TRANSFORMERS_ENCODER_OPTION.md`):

| Format | Default encoder | Own encoder still in the tree | Last comparison (33 inputs, library commit `9e951e9`) |
|---|---|---|---|
| ASTERIX CAT062 | library | `src/cat062.rs`, 582 lines | 25 of 25 blocks byte-identical, 397 of 397 fields equal |
| CoT | library | `src/cot.rs`, 264 lines | 588 of 594 fields equal; the 6 are the same instant written with and without `.000` |
| SAPIENT | own | `src/sapient.rs`, 699 lines | 685 of 719 fields equal; the library does not write `object_info` |

Three things follow from keeping both.

- **The pins drift.** The translator embeds library files at `9e951e9`, the
  `xf-ingest` kid at `d57d361`, and the library's main is `5daad57`. A pack
  fix reaches each copy separately. #43 moves the translator to `1b6f94a` and
  is open.
- **A field the record cannot hold is lost before any encoder sees it.**
  Canonical Track v2 (`schemas/`, `additionalProperties: false`) is the only
  thing a kid may hand the translator. A value with no property there, such
  as a radar cross section, a point of origin or a Doppler velocity, cannot
  reach an output, whichever encoder runs. The library's shared model has
  keys this schema lacks (`radar.rcs_m2`), and packs that write them
  (`cot-xml-radar`, `asterix-cat062-rcs`).
- **Every kid repeats the mapping work.** The kid package contract gives each
  kid `schemas/`, `mappings/`, `lookups/`, `decoder/` and `mapper/`. Two
  kids for the same sensor are two mappings, and nothing checks that either
  one carries every field its decoder reads. `xf-ingest` already shows the
  other shape: its `mappings/canonical-track-v2.json` is a description, and
  the conversion is the pack.

goat-transformers ADR 0006 (Proposed) makes the library the single home of
every format for the goat family. This record is Open Billie's side of it.

## Decision

1. **The library is the only encoder.** `src/cot.rs` and `src/cat062.rs`
   are deleted, with `BILLIE_COT_ENCODER`, `BILLIE_CAT062_ENCODER`, the
   `native` value and the build without the `goat-transformers` feature.
   `src/sapient.rs` and `BILLIE_SAPIENT_ENCODER` are deleted when the library
   writes `object_info` and the comparison shows no field different.
2. **Node-owned values stay in the translator, as context.** The scoped track
   identity, the CoT stale time and `how`, the CAT062 SAC and SIC, and the
   SAPIENT node identifier, timestamp and ULIDs are computed here and passed
   to the library as context keys, as `src/goat_path.rs` does now. The code
   that computes them moves out of the encoder modules before those are
   deleted. Request parsing, kid authentication, output authorization and
   publishing do not change.
3. **A kid selects packs; it carries no mapping.** A kid package declares its
   source (listener, framing) and names a source pack and the context it
   supplies. Its `schemas/`, `mappings/`, `lookups/` and `mapper/` content
   becomes that pack. A pack for a public format lives in goat-transformers.
   A pack for a format that is not public stays outside this repository,
   in the private overlay that pins the library, and reaches a node inside
   the kid's own bundle. `billie mapper generate` emits a pack and its
   "Not carried" list in place of a mapper plan.
4. **The record follows the shared model.** The translator accepts the
   library's shared-model keys for a track, with Canonical Track v2 kept as
   one input pack (`canonical-track-v2`) for kids already built against it.
   A value the shared model holds reaches every output pack that writes it,
   without a schema change here.
5. **One pin.** The repository pins one library commit in one file. The
   translator's and each kid's embedded pack and model files are copies of
   that commit, checked by `tools/sync_goat_transformers_packs.py` and
   `SHA256SUMS`. No embedded file is edited here.
6. **Deletion follows parity.** Each removal is one pull request. Its test
   runs both paths on the same inputs and compares field by field; a
   difference is recorded as a defect of the removed code, a value the pack
   lists as not carried, or a blocker.

## Modules, in order

| # | Module | Removed | Condition |
|---|---|---|---|
| 1 | One pin | the second `COMMIT` file; #43 lands | translator and `xf-ingest` comparison tests pass at the same commit |
| 2 | CAT062 | `src/cat062.rs`, `BILLIE_CAT062_ENCODER` | 25 of 25 byte-identical at the new pin; the SAC/SIC code moved to context |
| 3 | CoT | `src/cot.rs`, `BILLIE_COT_ENCODER` | the `.000` difference accepted in `docs/UPGRADING.md`; identity and stale code moved to context |
| 4 | Shared-model record | the closed track schema as the only input | a kid can send `radar.rcs_m2` and the CoT and CAT062 outputs carry it |
| 5 | Kid contract | `mappings/`, `lookups/`, `mapper/` from `kids/_template` and the contract; the OETF example's Python, Rust and TypeScript mappers | the OETF example decodes through a public pack and passes its conformance vectors |
| 6 | SAPIENT | `src/sapient.rs`, `BILLIE_SAPIENT_ENCODER` | the library writes `object_info`; 719 of 719 fields equal |

## What is built and what is not

| Piece | Status |
|---|---|
| Library encoder for CoT and CAT062, default in a normal build | Built (#35); not deployed |
| Library encoder for SAPIENT, selectable | Built; 34 of 719 fields differ |
| `xf-ingest`: a kid whose whole conversion is packs | Built |
| Context computation separate from the encoder modules | Not built |
| A record wider than Canonical Track v2 | Not built |
| A sensor kid that carries a pack and no mapping | Not built |
| `billie mapper generate` emitting a pack | Not built |

## Consequences

- A format fix is made once, in the library, and reaches the node at the next
  pin move.
- The fallback to an own encoder goes away. Rolling back a bad pack is a pin
  revert and a new platform release.
- The kid package contract and the authoring guide change. Kids built against
  the current contract keep working through the `canonical-track-v2` pack.
- The OETF example loses its three mappers and gains a pack, which
  makes it a smaller example of the thing a kid author now writes.
- Encoding time moves to the library's Rust engine in the same process. It is
  not measured on a node.

## Alternatives considered

- **Keep both encoders selectable.** Today's state. It keeps 1,545 lines of
  encoder, 582 of which the CAT062 comparison shows byte-identical to the
  library, and a second place for every future format fix.
- **Keep kid mappings and retire only the encoders.** The fields lost in a
  kid's mapping are lost before the translator. Moving only the encoders
  leaves that unchecked.
- **Widen Canonical Track v2 field by field.** Each new value would need a
  schema change here and a key in the library. Accepting shared-model keys
  makes the library's model governance the one place that decides.
