//! billie-oetf — Rust decoder, builder and CAT-062 / CoT / SAPIENT mapper for OETF
//! (Open Example Track Format).
//!
//! Shares its schemas, maps and lookup tables with the TypeScript and Python
//! implementations (embedded at build time from `packages/oetf/shared`);
//! `shared/conformance` holds the golden vectors all three must reproduce.
//!
//! ```no_run
//! use billie_oetf::{Mapper, OetfDecoder};
//! let mut decoder = OetfDecoder::new();
//! let mapper = Mapper::bundled();
//! # let datagram: &[u8] = &[];
//! for rec in decoder.feed(datagram) {
//!     for i062 in mapper.translate("oetf", &rec, "asterix-cat062") {
//!         println!("{}", i062.fields);
//!     }
//! }
//! ```

pub mod builder;
pub mod decoder;
pub mod mapper;
pub mod parser;

/// Shared artifacts embedded by `build.rs`: `(relative path, JSON text)`.
pub mod bundled {
    include!(concat!(env!("OUT_DIR"), "/bundled.rs"));
}

pub use builder::{build_frame, build_sensor_status, build_track_report, FrameHeader, SensorStatus, Track};
pub use decoder::{crc16, DecodedRecord, FramingError, OetfDecoder, FORMAT_VERSION, MAGIC};
pub use mapper::{Mapper, Translated};

/// Contract-version constant. Bumped on breaking changes to the runtime shape.
pub const RUNTIME_SHAPE_VERSION: u32 = 1;
/// Protocol name as referenced in mapping files.
pub const PROTOCOL_NAME: &str = "oetf";
