use crate::{
    Cat062EncodeError, Cat062Encoder, Cat062Options, CotEncodeError, CotEncoder, CotOptions,
    EncoderFormat, SapientEncodeError, SapientEncoder, SapientOptions, TranslateRequest,
};

/// Node-level options used by the shared format dispatcher.
#[derive(Clone, Debug, Default)]
pub struct EncodeOptions {
    pub cot: CotOptions,
    pub cat062: Cat062Options,
    pub sapient: SapientOptions,
    /// Which encoder writes each output format. Native for every format
    /// unless node configuration selects otherwise.
    pub encoders: EncoderSelection,
}

/// The encoder that writes one output format.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum EncoderPath {
    /// The encoder written in this crate.
    #[default]
    Native,
    /// The goat-transformers library with the packs embedded in this crate.
    /// Present only in a build with the cargo feature `goat-transformers`.
    GoatTransformers,
}

impl EncoderPath {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Native => "native",
            Self::GoatTransformers => "goat-transformers",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "native" => Some(Self::Native),
            "goat-transformers" => Some(Self::GoatTransformers),
            _ => None,
        }
    }
}

/// Per-format encoder selection, read from node configuration.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct EncoderSelection {
    pub cot: EncoderPath,
    pub cat062: EncoderPath,
    pub sapient: EncoderPath,
}

impl EncoderSelection {
    /// Environment variable that selects the encoder of each output format.
    pub const VARIABLES: [(EncoderFormat, &'static str); 3] = [
        (EncoderFormat::Cot, "BILLIE_COT_ENCODER"),
        (EncoderFormat::AsterixCat062, "BILLIE_CAT062_ENCODER"),
        (EncoderFormat::Sapient, "BILLIE_SAPIENT_ENCODER"),
    ];

    pub fn path(&self, format: EncoderFormat) -> EncoderPath {
        match format {
            EncoderFormat::Cot => self.cot,
            EncoderFormat::AsterixCat062 => self.cat062,
            EncoderFormat::Sapient => self.sapient,
        }
    }

    /// Read the selection from the service environment. An unset or empty
    /// variable selects the native encoder.
    pub fn from_env() -> Result<Self, String> {
        Self::from_lookup(|name| std::env::var(name).ok())
    }

    /// Read the selection through `lookup`, which returns the value of a
    /// named variable. A value other than `native` or `goat-transformers`
    /// is an error, and so is `goat-transformers` in a build without it.
    pub fn from_lookup(lookup: impl Fn(&str) -> Option<String>) -> Result<Self, String> {
        let mut selection = Self::default();
        for (format, variable) in Self::VARIABLES {
            let Some(value) = lookup(variable).filter(|value| !value.is_empty()) else {
                continue;
            };
            let path = EncoderPath::parse(&value).ok_or_else(|| {
                format!("{variable} must be 'native' or 'goat-transformers', not '{value}'")
            })?;
            match format {
                EncoderFormat::Cot => selection.cot = path,
                EncoderFormat::AsterixCat062 => selection.cat062 = path,
                EncoderFormat::Sapient => selection.sapient = path,
            }
        }
        selection.check()?;
        Ok(selection)
    }

    /// Confirm this build can run the selection: the library is compiled in
    /// and its embedded packs load.
    pub fn check(&self) -> Result<(), String> {
        if Self::VARIABLES
            .iter()
            .all(|(format, _)| self.path(*format) == EncoderPath::Native)
        {
            return Ok(());
        }
        library_check()
    }
}

#[cfg(feature = "goat-transformers")]
fn library_check() -> Result<(), String> {
    crate::goat_path::check().map_err(|error| error.message)
}

#[cfg(not(feature = "goat-transformers"))]
fn library_check() -> Result<(), String> {
    Err(LibraryEncodeError::not_built().message)
}

/// A failure of the goat-transformers encoder path.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LibraryEncodeError {
    pub code: &'static str,
    pub message: String,
}

impl LibraryEncodeError {
    #[cfg(not(feature = "goat-transformers"))]
    fn not_built() -> Self {
        Self {
            code: "encoder_unavailable",
            message: "the goat-transformers encoder is selected, but this translator was built without the cargo feature 'goat-transformers'".to_owned(),
        }
    }
}

impl Default for Cat062Options {
    fn default() -> Self {
        Self {
            default_source: None,
            sources: Default::default(),
        }
    }
}

/// Encoded bytes and their output format metadata.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EncodedPayload {
    pub kid: String,
    pub output_name: String,
    pub format: EncoderFormat,
    pub content_type: &'static str,
    pub bytes: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EncodeDispatchError {
    Cot(CotEncodeError),
    Cat062(Cat062EncodeError),
    Sapient(SapientEncodeError),
    UnsupportedFormat(EncoderFormat),
    /// The goat-transformers encoder path could not produce the output.
    Library(LibraryEncodeError),
}

/// Select and run the shared encoder requested by a validated translation request.
pub fn encode_request(
    request: &TranslateRequest,
    options: &EncodeOptions,
) -> Result<EncodedPayload, EncodeDispatchError> {
    if options.encoders.path(request.format) == EncoderPath::GoatTransformers {
        #[cfg(feature = "goat-transformers")]
        return crate::goat_path::encode_request(request, options);
        #[cfg(not(feature = "goat-transformers"))]
        return Err(EncodeDispatchError::Library(LibraryEncodeError::not_built()));
    }
    match request.format {
        EncoderFormat::Cot => CotEncoder::new(options.cot.clone())
            .encode_for_kid(&request.record, &request.kid)
            .map(|bytes| EncodedPayload {
                kid: request.kid.clone(),
                output_name: request.output_name.clone(),
                format: EncoderFormat::Cot,
                content_type: "application/xml",
                bytes,
            })
            .map_err(EncodeDispatchError::Cot),
        EncoderFormat::AsterixCat062 => Cat062Encoder::new(options.cat062.clone())
            .encode_for_kid(&request.record, &request.kid)
            .map(|bytes| EncodedPayload {
                kid: request.kid.clone(),
                output_name: request.output_name.clone(),
                format: EncoderFormat::AsterixCat062,
                content_type: "application/vnd.asterix.category-062",
                bytes,
            })
            .map_err(EncodeDispatchError::Cat062),
        EncoderFormat::Sapient => SapientEncoder::new(options.sapient.clone())
            .encode_for_kid(&request.record, &request.kid)
            .map(|bytes| EncodedPayload {
                kid: request.kid.clone(),
                output_name: request.output_name.clone(),
                format: EncoderFormat::Sapient,
                content_type: "application/vnd.sapient.protobuf",
                bytes,
            })
            .map_err(EncodeDispatchError::Sapient),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{parse_request, EncoderFormat};
    use serde_json::Value;

    fn request_for(format: &str) -> TranslateRequest {
        let mut input: Value = serde_json::from_str(include_str!(
            "../../../../schemas/examples/oetf-translation-request.json"
        ))
        .unwrap();
        input["target"]["format"] = serde_json::json!(format);
        if format == "asterix-cat062" {
            input["record"]["confirmed"] = serde_json::json!(true);
        }
        parse_request(&input).unwrap()
    }

    #[test]
    fn dispatches_to_cot_and_declares_xml_media_type() {
        let result = encode_request(&request_for("cot"), &EncodeOptions::default()).unwrap();
        assert_eq!(result.format, EncoderFormat::Cot);
        assert_eq!(result.kid, "oetf");
        assert_eq!(result.output_name, "tracks-cot");
        assert_eq!(result.content_type, "application/xml");
        let xml = String::from_utf8(result.bytes).unwrap();
        assert!(xml.starts_with("<event "));
        assert!(xml.contains("uid=\"oetf/263/311/fixture-1\""));
    }

    #[test]
    fn dispatches_to_cat062_with_node_source_configuration() {
        let options = EncodeOptions {
            cat062: Cat062Options {
                default_source: Some(crate::Cat062SourceIdentifier { sac: 4, sic: 22 }),
                sources: Default::default(),
            },
            ..EncodeOptions::default()
        };
        let result = encode_request(&request_for("asterix-cat062"), &options).unwrap();
        assert_eq!(result.format, EncoderFormat::AsterixCat062);
        assert_eq!(result.content_type, "application/vnd.asterix.category-062");
        assert_eq!(result.bytes[0], 62);
        assert_eq!(&result.bytes[6..8], &[4, 22]);
    }

    #[test]
    fn cat062_source_assignment_is_scoped_by_authenticated_kid() {
        let mut request = request_for("asterix-cat062");
        let options = EncodeOptions {
            cat062: Cat062Options {
                default_source: None,
                sources: std::collections::HashMap::from([
                    (
                        ("oetf".to_owned(), "263".to_owned()),
                        crate::Cat062SourceIdentifier { sac: 1, sic: 7 },
                    ),
                    (
                        ("another-kid".to_owned(), "263".to_owned()),
                        crate::Cat062SourceIdentifier { sac: 2, sic: 7 },
                    ),
                ]),
            },
            ..EncodeOptions::default()
        };
        let encoded = encode_request(&request, &options).unwrap();
        assert_eq!(&encoded.bytes[6..8], &[1, 7]);
        request.kid = "another-kid".to_owned();
        let encoded = encode_request(&request, &options).unwrap();
        assert_eq!(&encoded.bytes[6..8], &[2, 7]);
    }

    #[test]
    fn selects_native_encoders_unless_configured_per_format() {
        assert_eq!(
            EncoderSelection::from_lookup(|_| None).unwrap(),
            EncoderSelection::default()
        );
        assert_eq!(EncoderSelection::default().cot, EncoderPath::Native);
        let explicit = EncoderSelection::from_lookup(|name| {
            (name == "BILLIE_SAPIENT_ENCODER").then(|| "native".to_owned())
        })
        .unwrap();
        assert_eq!(explicit, EncoderSelection::default());
        let error = EncoderSelection::from_lookup(|name| {
            (name == "BILLIE_COT_ENCODER").then(|| "fastest".to_owned())
        })
        .unwrap_err();
        assert_eq!(
            error,
            "BILLIE_COT_ENCODER must be 'native' or 'goat-transformers', not 'fastest'"
        );
    }

    #[cfg(not(feature = "goat-transformers"))]
    #[test]
    fn refuses_the_library_encoder_in_a_build_without_it() {
        let error = EncoderSelection::from_lookup(|name| {
            (name == "BILLIE_CAT062_ENCODER").then(|| "goat-transformers".to_owned())
        })
        .unwrap_err();
        assert!(error.contains("built without the cargo feature 'goat-transformers'"));
        let options = EncodeOptions {
            encoders: EncoderSelection {
                cot: EncoderPath::GoatTransformers,
                ..EncoderSelection::default()
            },
            ..EncodeOptions::default()
        };
        match encode_request(&request_for("cot"), &options).unwrap_err() {
            EncodeDispatchError::Library(error) => assert_eq!(error.code, "encoder_unavailable"),
            other => panic!("unexpected error: {other:?}"),
        }
    }

    #[test]
    fn requires_node_identity_for_sapient_output() {
        assert_eq!(
            encode_request(&request_for("sapient"), &EncodeOptions::default()).unwrap_err(),
            EncodeDispatchError::Sapient(crate::SapientEncodeError {
                code: "invalid_configuration",
                message: "SAPIENT node UUID is missing; configure the node identity or set BILLIE_SAPIENT_NODE_ID".to_owned(),
            })
        );
    }
}
