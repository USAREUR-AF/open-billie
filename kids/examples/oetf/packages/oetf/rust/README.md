# billie-oetf (Rust)

This package contains the Rust OETF decoder, frame builder, shared-map executor, and a deployable TCP/UDP runtime adapter. The runtime decodes input, applies the shared OETF-to-canonical map, then sends a versioned request to the local Billie Rust translator over its Unix socket. Billie core owns the shared CoT, ASTERIX CAT062, and SAPIENT encoders.

## Usage

```rust
use billie_oetf::{Mapper, OetfDecoder};

let mut decoder = OetfDecoder::new();
let mapper = Mapper::bundled();
for rec in decoder.feed(&datagram) {
    for track in mapper.translate("oetf", &rec, "billie-canonical") {
        println!("{}", track.fields);
    }
}
let errors = decoder.take_recent_errors();
```

```sh
cargo run --example translate -- 4f455446011046...             # every target
cargo run --example translate -- --to cot 4f455446011046...    # or one target
```

## Shared artifacts, embedded

`build.rs` walks [`../shared`](../shared/) (`schemas/`, `mappings/`, `lookups/`), then `include_str!`s every JSON file into the crate. The binary is self-contained, but it is still built from the single shared copy. A new map file is picked up on the next build without a code change. `Mapper::from_dirs` loads maps from disk instead, for a deployment overlay.

## Runtime adapter

`src/bin/billie-oetf-runtime.rs` implements the same kid-to-translator boundary as the Python and TypeScript runtimes. It accepts `BILLIE_INPUT_BIND`, `BILLIE_INPUT_PORT`, `BILLIE_INPUT_TRANSPORT` (`udp` or `tcp`), and `BILLIE_TRANSLATOR_SOCKET`. TCP uses one connection at a time and a fresh decoder per connection; UDP uses the declared datagram listener. Each canonical track is submitted to the translator for CoT, CAT062, and SAPIENT outputs. The runtime does not configure Zenoh or read fabric credentials.

The kid manifest marks Rust deployable and selects the runtime with `Containerfile.rust`. Choose it from the kid wizard or run `billie kid build <package> --decoder-language rust --platform linux/arm64` (or `linux/amd64`).

## Build and test

No local toolchain is required to build the image; the Containerfile pins its Rust compiler. For local tests, use Rust/Cargo 1.78 or newer because this package's lockfile uses format v4. CI runs Rust 1.85.1. Run the build in a container:

```sh
docker run --rm -v "$PWD/../../..:/src" -w /src/packages/oetf/rust \
  -v oetf-cargo-target:/target -e CARGO_TARGET_DIR=/target rust:1-slim cargo test
```

If you have a local toolchain, `cargo test` works too. Build the runtime with `cargo build --release --bin billie-oetf-runtime`.
