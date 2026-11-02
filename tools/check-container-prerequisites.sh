#!/usr/bin/env bash
# Check that a local image engine is installed and running before a build.
set -u

purpose="${1:-kid}"
case "$purpose" in
  kid|platform) ;;
  *) printf 'Usage: bash tools/check-container-prerequisites.sh [kid|platform]\n' >&2; exit 2 ;;
esac

engine_override="${BILLIE_CONTAINER_ENGINE:-}"
if [ -n "$engine_override" ] && [ "$engine_override" != docker ] && [ "$engine_override" != podman ]; then
  printf 'BILLIE_CONTAINER_ENGINE must be docker or podman (got: %s).\n' "$engine_override" >&2
  exit 2
fi

docker_cli=""
if command -v docker >/dev/null 2>&1; then
  docker_cli=docker
elif command -v docker.exe >/dev/null 2>&1; then
  docker_cli=docker.exe
fi

podman_state=missing
if command -v podman >/dev/null 2>&1; then
  if podman info >/dev/null 2>&1; then podman_state=ready; else podman_state=stopped; fi
fi

docker_state=missing
if [ -n "$docker_cli" ]; then
  if "$docker_cli" info >/dev/null 2>&1; then
    if [ "$purpose" = kid ] && ! "$docker_cli" buildx version >/dev/null 2>&1; then
      docker_state=no-buildx
    else
      docker_state=ready
    fi
  else
    docker_state=stopped
  fi
fi

printf 'Checking container build prerequisites (%s build):\n' "$purpose"
case "$podman_state" in
  ready) printf '  [OK] Podman is installed and its engine responds.\n' ;;
  stopped) printf '  [NEEDS START] Podman is installed, but its engine does not respond. Start it with: podman machine start\n' ;;
  missing) printf '  [MISSING] Podman is not installed.\n' ;;
esac
case "$docker_state" in
  ready) printf '  [OK] Docker is installed, its engine responds, and required build features are available.\n' ;;
  no-buildx) printf '  [MISSING] Docker is running, but Docker Buildx is required for kid package builds.\n' ;;
  stopped) printf '  [NEEDS START] Docker is installed, but its engine does not respond. Start Docker Desktop.\n' ;;
  missing) printf '  [MISSING] Docker is not installed.\n' ;;
esac

if [ -n "$engine_override" ]; then
  selected="$engine_override"
elif [ "$podman_state" = ready ]; then
  selected=podman
elif [ "$docker_state" = ready ]; then
  selected=docker
else
  printf '\nNo usable container engine is ready. Install and start Docker Desktop or Podman, then rerun this check.\n' >&2
  exit 2
fi

if [ "$selected" = podman ] && [ "$podman_state" != ready ]; then
  printf '\nSelected engine Podman is not ready. Start its machine with: podman machine start\n' >&2
  exit 2
fi
if [ "$selected" = docker ] && [ "$docker_state" != ready ]; then
  if [ "$docker_state" = no-buildx ]; then
    printf '\nSelected Docker engine needs the Buildx plugin for kid package builds.\n' >&2
  else
    printf '\nSelected engine Docker is not ready. Start Docker Desktop and retry.\n' >&2
  fi
  exit 2
fi

printf 'Selected container engine: %s\n' "$selected"
