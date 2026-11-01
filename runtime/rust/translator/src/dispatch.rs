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
}

/// Select and run the shared encoder requested by a validated translation request.
pub fn encode_request(
    request: &TranslateRequest,
    options: &EncodeOptions,
) -> Result<EncodedPayload, EncodeDispatchError> {
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
