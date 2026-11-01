use billie_translator::{parse_request, Cat062Encoder, Cat062Options, CotEncoder, EncoderFormat};
use serde_json::Value;

#[test]
fn translates_oetf_mapper_fixture_through_cot_encoder() {
    let input: Value = serde_json::from_str(include_str!(
        "../../../../schemas/examples/oetf-translation-request.json"
    ))
    .unwrap();
    let request = parse_request(&input).unwrap();
    assert_eq!(request.kid, "oetf");
    assert_eq!(request.format, EncoderFormat::Cot);
    assert_eq!(request.record.track_id, "311");
    assert_eq!(
        request.record.classification.unwrap(),
        billie_translator::Classification::Uas
    );
    let cot = String::from_utf8(
        CotEncoder::default()
            .encode_for_kid(&request.record, &request.kid)
            .unwrap(),
    )
    .unwrap();
    assert!(cot.contains("type=\"a-u-A-M-F-Q\""));
    assert!(cot.contains("uid=\"oetf/263/311/fixture-1\""));
    assert!(cot.contains("lat=\"38.8977\""));
    let cat062 = Cat062Encoder::new(Cat062Options {
        default_source: Some(billie_translator::Cat062SourceIdentifier { sac: 1, sic: 7 }),
        ..Cat062Options::default()
    })
    .encode_for_kid(&request.record, &request.kid)
    .unwrap();
    assert_eq!(cat062[0], 62);
    assert_eq!(&cat062[6..8], &[1, 7]);
    assert_eq!(u16::from_be_bytes([cat062[23], cat062[24]]), 311);
}
