//! billie-bite-kid: an Open Billie kid runtime with no sensor code in it.
//!
//! The decoder is the first-bite `bite` library reading a dictionary (a
//! directory of JSON files that gives the bit range and type of every field).
//! The mapper executes mapping files that bind decoded fields to Canonical
//! Track v2. The message set, the mapping and the logical outputs are all
//! data in the kid package; this crate holds none of them.
//!
//! ```no_run
//! use billie_bite_kid::{Decoder, Mapper};
//! use std::path::Path;
//!
//! let decoder = Decoder::load(Path::new("schemas/weather-station"), None)?;
//! let mapper = Mapper::from_dirs(Path::new("mappings"), Path::new("lookups"))?;
//! # let datagram: &[u8] = &[];
//! let record = decoder.decode(datagram)?;
//! if let Some(mapped) = mapper.translate(&record, "2026-01-01T00:00:00.000Z") {
//!     println!("{}", mapped.track);
//! }
//! # Ok::<(), String>(())
//! ```

pub mod decoder;
pub mod mapper;
pub mod request;

pub use decoder::{Decoder, Record};
pub use mapper::{Mapped, Mapper};
pub use request::{rfc3339_millis, translation_request};
