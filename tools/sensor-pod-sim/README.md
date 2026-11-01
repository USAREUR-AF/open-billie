# Synthetic OETF sensor pod

This container is a synthetic OETF sensor. It sends one test-flagged and simulated Track Report per second over UDP or TCP to the configured destination. The Compose profile uses the documentation-only placeholder `192.0.2.20:3401/TCP`; replace it with the Billie sensor-facing address in your test setup. The packet source is selected by the container engine's outbound route, and the container does not bind the workstation's physical Ethernet address.

The frames use the public OETF example protocol and contain no proprietary sensor data. The destination and port can be changed in compose.yaml or overridden on a one-off run.

## Start continuously with Docker Compose

Run from the Open Billie repository root:

    docker compose -f tools/sensor-pod-sim/compose.yaml up --build -d

Follow the sensor output:

    docker compose -f tools/sensor-pod-sim/compose.yaml logs -f sensor-pod

Stop it:

    docker compose -f tools/sensor-pod-sim/compose.yaml down

The simulator continues while Billie is torn down. TCP mode retries its connection until the listener is available; UDP mode sends without a connection. Configure the kid for the same transport, address, and port shown in the container logs.

## Podman or one-off container

From the repository root, build and run with Podman:

    podman build -f tools/sensor-pod-sim/Containerfile -t open-billie/oetf-sensor-sim:local .
    podman run --rm --name open-billie-oetf-sensor --network slirp4netns \
      -e SENSOR_TRANSPORT=tcp -e SENSOR_DESTINATION=192.0.2.20 -e SENSOR_PORT=3401 \
      -e SENSOR_INTERVAL_SECONDS=1 -e SENSOR_COUNT=0 \
      open-billie/oetf-sensor-sim:local

Use Ctrl+C to stop the one-off run. Set SENSOR_COUNT to a positive integer for a finite smoke test.

## Change the destination

Edit the service environment in compose.yaml, then recreate it:

    docker compose -f tools/sensor-pod-sim/compose.yaml up --build --force-recreate -d

For a one-off Docker run with a different destination or transport:

    docker run --rm --name open-billie-oetf-sensor \
      -e SENSOR_TRANSPORT=tcp -e SENSOR_DESTINATION=192.0.2.20 -e SENSOR_PORT=3400 \
      -e SENSOR_INTERVAL_SECONDS=1 -e SENSOR_COUNT=0 \
      open-billie/oetf-sensor-sim:local

Use the node's actual sensor-facing IP. A container on a bridged network is NATed by the host/container engine. Ensure the node's listener firewall permits the observed sender address. The sensor transmits outbound only and requires no privileged mode or host port publishing.
