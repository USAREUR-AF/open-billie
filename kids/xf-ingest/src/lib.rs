//! billie-xf-ingest: an Open Billie kid for sensors whose output is already a
//! standard format.
//!
//! Every message is converted by goat-transformers (the `goat-xf-pipe`
//! pipeline, its transports and framers, and the engine reading packs) to
//! Canonical Track v2, and each converted track is handed to the Open Billie
//! translator once per declared output. The kid holds no code for any format:
//! the input format is the name of a pack, chosen by configuration.
//!
//! - [`settings`] turns the kid's environment into a `goat-xf-pipe` command
//!   line.
//! - [`translator`] is the `billie:` output: the translator socket.

pub mod settings;
pub mod translator;
