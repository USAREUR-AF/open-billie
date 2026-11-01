//! Typed, strict parser for the versioned kid-to-translator request contract.
//!
//! Protocol translators and encoders consume [`TranslateRequest`] only after
//! this validation layer has checked the canonical record and target selector.

mod cat062;
mod cot;
mod dispatch;
#[cfg(unix)]
mod ipc;
#[cfg(unix)]
mod publisher;
mod request;
mod sapient;

pub use cat062::{
    parse_cat062_source_config_json, parse_source_identifiers_json, Cat062EncodeError,
    Cat062Encoder, Cat062Options, Cat062SourceConfig, Cat062SourceIdentifier,
};
pub use cot::{CotEncodeError, CotEncoder, CotOptions};
pub use dispatch::{encode_request, EncodeDispatchError, EncodeOptions, EncodedPayload};
#[cfg(unix)]
pub use ipc::{serve_unix, PublishError, MAX_REQUEST_BYTES};
#[cfg(unix)]
pub use publisher::{publish_to_local_zenoh, publish_to_rest};
pub use request::{
    parse_request, CanonicalTrack, Classification, ContractError, EncoderFormat, Identifier,
    Position, PositionUncertainty, TranslateRequest, Velocity,
};
pub use sapient::{SapientEncodeError, SapientEncoder, SapientOptions};

/// Contract version accepted by this translator release.
pub const API_VERSION: &str = "billie.dev/translation-v1";
pub const TRACK_VERSION: &str = "billie.dev/track-v2";
