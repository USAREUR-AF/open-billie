# Architecture and data boundary

Open Billie is the sensor-neutral platform layer. It provisions and operates the node, defines the generic kid package contract, and provides public-standard components where redistribution is permitted.

Production kid packages may contain sensor-specific code and data. Maintain them outside this repository; do not add them as submodules or bundle them into the Open Billie platform release. The synthetic OETF package is an in-repository example and contains no proprietary sensor data. A deployment may install an authorized production kid artifact through an external package or image source.

Kid authors use the [kid package contract](KID_PACKAGE_CONTRACT.md) and [template](../../kids/_template/README.md). Decoders, schemas, mappings, lookups, and sensor-specific test vectors stay in that kid's repository and independently versioned package. Bundle signing is planned; current bundles use checksums only.

Allowed examples use synthetic input only. Real protocol samples, sensor field maps, private lookups, interface documents, deployment endpoints, and credentials are excluded from source, tests, documentation, and release artifacts.

Before code is moved into this project, record its source and redistribution status. The release builder must use an explicit allowlist and the CI pipeline must inspect both source and packaged output.
