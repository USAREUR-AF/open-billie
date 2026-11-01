# Canonical Track v2

Canonical Track is the language-neutral record produced by a kid mapper and consumed by the shared translator. The schema is [canonical-track-v2.schema.json](canonical-track-v2.schema.json); the wrapper is [translation-request-v1.schema.json](translation-request-v1.schema.json).

## Required fields

- `trackId`: stable source track identifier.
- `sourceId`: stable identifier for the source namespace. Different sources that can reuse track numbers need distinct IDs.
- `trackGeneration`: identifier for one lifetime of a track ID within a source. Advance it when the source recycles `trackId`; do not derive it from `observedAt`.
- `observedAt`: RFC 3339 date-time of the observation.
- `position.latitudeDeg` and `position.longitudeDeg`: WGS-84 geodetic degrees.

The stable logical identity is `(authenticated kid, sourceId, trackId, trackGeneration)`. The translator obtains the kid from its authenticated local socket peer; the mapper supplies the source and generation. A translator rejects records missing required fields and does not invent measurements.

## Optional fields and units

- `position.altitudeM`: metres above the WGS-84 ellipsoid.
- `velocity.eastMps`, `northMps`, `upMps`: local east/north/up metres per second; east and north are required together.
- `classification`: `unknown`, `fixed-wing-aircraft`, `rotary-wing-aircraft`, `uas`, `balloon`, `bird`, `vehicle`, `clutter`, or `other`.
- `confidence`: normalized range 0 through 1.
- `positionUncertainty`: one-sigma east, north, and up values in metres.
- `identifiers`: namespaced identifiers representable by the chosen output format.
- `testData`, `headerSimulated`, `simulated`, `confirmed`, `coasting`, `finalUpdate`: source-status booleans. Preserve source distinctions. Omitted fields mean unknown/not stated; translators must not silently convert omission to `false`.

The CAT062 Track Status item requires a confirmation state. If `confirmed` is omitted, the CAT062 encoder rejects that record because the format cannot represent unknown confirmation. CoT and SAPIENT leave the status unstated when the field is omitted.

## OETF mapping

The synthetic OETF mapper converts its timestamp to RFC 3339, IDs to strings, coordinates to WGS-84 degrees, altitude and velocity to metres and metres per second, and status bits to explicit booleans. Its fixed `trackGeneration` is fixture-only: production mappers must advance generations when source track IDs are reused.

## Output identity and limits

CoT and SAPIENT identities include the authenticated kid and `(sourceId, trackId, trackGeneration)`. CAT062 uses SAC/SIC plus its 12-bit track number and cannot carry `trackGeneration`; configure a unique SAC/SIC assignment per kid/source pair. The translator rejects a missing assignment when the map is configured. Target-specific required fields and omitted optional fields are validated and documented by each encoder.
