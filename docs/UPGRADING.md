# Upgrade notes

## Platform 0.2.x to 0.3.0

Platform 0.3.0 changes the kid-to-translator contract from `billie.dev/track-v1` to `billie.dev/track-v2`. This is a breaking change: v1 kid runtimes are not compatible with the 0.3.0 translator. Rebuild each kid from its source after updating its mapper and canonical output to the v2 schema, increment the kid package version, then install and activate the rebuilt bundle. Keep the previous platform and kid artifacts until the new deployment passes `billie verify` and sensor-output acceptance.

The in-repository OETF example is synthetic and has been updated to emit v2 records. Proprietary kid source is not needed to upgrade the platform; each sensor owner must rebuild their own kid using the [kid authoring guide](KID_PACKAGE_AUTHORING_GUIDE.md).

### CAT062 source assignments

Platform 0.3.0 continues to read the legacy global file shape:

```json
{"sources":{"sensor-a":{"sac":4,"sic":20}}}
```

The translator keeps those assignments available to all kids as a compatibility fallback, so a legacy file does not prevent translator startup. Resolution order is exact `(kid, sourceId)` assignment, legacy global assignment until migrated, then the optional node default. Configure the node default for a single-source setup or as a fallback using a pair authorized by the sensor-system authority:

```sh
sudo billie cat062 default set --sac <0-255> --sic <0-255>
sudo billie cat062 default show
```

Move to explicit per-kid assignments when ready:

```sh
sudo billie cat062 source list
sudo billie cat062 source migrate <kid-id>
sudo billie cat062 source list
```

Migration scopes the existing assignments to the selected kid and preserves the node default. Other kids use exact assignments when present, then the node default. Without either, CAT062 output for that source is rejected. Back up the file before migration if the old global behavior must be retained for another kid. Successful configuration commands restart the translator. Use `sudo billie cat062 default clear` to remove the fallback while preserving mapped assignments.

### Validation

After installing the platform and rebuilt kid:

```sh
sudo billie check
sudo billie apply
sudo billie verify
sudo billie kid status <kid-id>
sudo billie kid logs <kid-id>
```

Then send representative sensor traffic and verify the expected output with an authorized subscriber. `billie verify` validates platform service health; it does not prove that a sensor is transmitting or that an independent subscriber received data.
