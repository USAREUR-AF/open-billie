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

## Dependency security updates (2026-11-07)

The source dependency update addresses the 18 open Dependabot alerts observed
on 2026-11-07. Some advisories appear more than once because both the manifest
and lockfile, or both Vitest and its mocker package, were affected.

| Dependency | Updated resolution | Published advisories addressed |
|---|---|---|
| Vitest / @vitest/mocker | 4.1.12 | [GHSA-5xrq-8626-4rwp](https://github.com/advisories/GHSA-5xrq-8626-4rwp), [GHSA-82fw-gwwq-j7x9](https://github.com/advisories/GHSA-82fw-gwwq-j7x9), [GHSA-qxg6-89mg-rqv8](https://github.com/advisories/GHSA-qxg6-89mg-rqv8) |
| Tinypool | Removed from the dependency graph | [GHSA-85c8-ppgw-ccpr](https://github.com/advisories/GHSA-85c8-ppgw-ccpr), [GHSA-5gmw-xhrv-c9v3](https://github.com/advisories/GHSA-5gmw-xhrv-c9v3) |
| Vite | 6.4.5 | [GHSA-4w7w-66w2-5vf9](https://github.com/advisories/GHSA-4w7w-66w2-5vf9), [GHSA-fx2h-pf6j-xcff](https://github.com/advisories/GHSA-fx2h-pf6j-xcff), [GHSA-v6wh-96g9-6wx3](https://github.com/advisories/GHSA-v6wh-96g9-6wx3), [GHSA-698v-4r3x-3vcv](https://github.com/advisories/GHSA-698v-4r3x-3vcv), [GHSA-587h-7wmj-h5pm](https://github.com/advisories/GHSA-587h-7wmj-h5pm), [GHSA-r825-w8mm-5pxw](https://github.com/advisories/GHSA-r825-w8mm-5pxw), [GHSA-rq7h-c2jc-7f22](https://github.com/advisories/GHSA-rq7h-c2jc-7f22), [GHSA-9jrq-w75r-8gcw](https://github.com/advisories/GHSA-9jrq-w75r-8gcw) |
| esbuild | 0.25.12 | [GHSA-67mh-4wv8-2f99](https://github.com/advisories/GHSA-67mh-4wv8-2f99) |
| ansible-core (CI) | 2.21.6 | [GHSA-w8p5-mx5w-cpqj / CVE-2026-11332](https://github.com/advisories/GHSA-w8p5-mx5w-cpqj) |

After updating the checkout, reinstall the development dependencies:

```sh
python -m pip install --requirement requirements-ci.txt
cd kids/examples/oetf
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm audit
```

Use Python 3.12 and Node 22 to match CI. The JavaScript changes affect the
build/test workspace; the current multi-stage TypeScript runtime image does
not copy its development dependencies into the final stage. Reinstalling the
workspace does not update old images that were built with other packaging.

The platform Debian package obtains `ansible-core` from the node's configured
Ubuntu repositories. `requirements-ci.txt` is not used to install or upgrade
that package. Record the node's installed version with
`dpkg-query -W ansible-core`, inspect `apt-cache policy ansible-core`, and
check the applicable Ubuntu security notice and package changelog for
CVE-2026-11332 before declaring the node remediated. Distribution backports
cannot be judged from the upstream version number alone. Apply the approved
vendor security update through the normal node maintenance process; do not
replace the system Python installation with the CI pip environment.

The reported Ansible issue requires installation of a malicious Galaxy role.
Billie's tracked automation does not invoke `ansible-galaxy role install`;
operators should avoid untrusted Galaxy roles while checking their host
package status. This source update makes no claim that existing nodes or
previously built artifacts are patched.

On 2026-11-07, the updated workspace passed typechecking and all 30 TypeScript
tests; `pnpm audit` reported no known vulnerabilities. Python 3.12 platform
unit tests passed (51 tests), and all four playbooks passed syntax checking
with Ansible Core 2.21.6. A pip-audit check of the 15 resolved CI packages
(including transitive dependencies installed on the validation workstation)
reported no known vulnerabilities. Python transitive dependencies remain
unlocked, so repeat the audit for the actual CI/deployment environment.
These checks do not replace the artifact review gates in [SBOM_REVIEW.md](SBOM_REVIEW.md).
