# Embedded goat-transformers definitions

The files under `model/` and `packs/`, and `NOTICE`, are copied unchanged from [goat-transformers](https://github.com/USAREUR-AF/goat-transformers) at the commit in `COMMIT`. `SHA256SUMS` lists their SHA-256 digests. The translator embeds the definition files at build time when the cargo feature `goat-transformers` is on; see [the encoder option](../../../../docs/architecture/GOAT_TRANSFORMERS_ENCODER_OPTION.md).

Do not edit these files here. Change them in goat-transformers, move the `rev` in `../Cargo.toml` to the new commit, and run `python3 tools/sync_goat_transformers_packs.py` from the repository root.

goat-transformers is licensed under Apache-2.0, the license of this repository. `NOTICE` is its notice file; it states the third-party sources each pack and model module was written from.
