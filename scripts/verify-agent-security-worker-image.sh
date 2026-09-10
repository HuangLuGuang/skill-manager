#!/bin/bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 IMAGE amd64|arm64" >&2
    exit 2
fi

IMAGE="$1"
EXPECTED_ARCH="$2"

case "$EXPECTED_ARCH" in
    amd64|arm64) ;;
    *)
        echo "Unsupported architecture: ${EXPECTED_ARCH}" >&2
        exit 2
        ;;
esac

ACTUAL_ARCH="$(docker image inspect --format '{{.Architecture}}' "$IMAGE")"
if [ "$ACTUAL_ARCH" != "$EXPECTED_ARCH" ]; then
    echo "Image architecture mismatch: ${IMAGE} is ${ACTUAL_ARCH}, expected ${EXPECTED_ARCH}" >&2
    exit 1
fi

IMAGE_USER="$(docker image inspect --format '{{.Config.User}}' "$IMAGE")"
if [ "$IMAGE_USER" != "10001:10001" ]; then
    echo "Image user mismatch: ${IMAGE} uses ${IMAGE_USER}, expected 10001:10001" >&2
    exit 1
fi

HEALTHCHECK="$(docker image inspect --format '{{json .Config.Healthcheck.Test}}' "$IMAGE")"
if [ "$HEALTHCHECK" != '["CMD","python","/app/worker.py","--healthcheck"]' ]; then
    echo "Image healthcheck mismatch: ${HEALTHCHECK}" >&2
    exit 1
fi

docker run --rm --pull never \
    --platform "linux/${EXPECTED_ARCH}" \
    --network none \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --pids-limit 128 \
    --memory 512m \
    --cpus 1 \
    --entrypoint python \
    "$IMAGE" \
    -c "import pathlib,sys; sys.path.insert(0, '/app'); import worker; worker._touch_health(); assert worker._healthcheck() == 0; assert pathlib.Path('/app/licenses/LICENSE').is_file(); assert pathlib.Path('/app/licenses/NOTICE').is_file(); assert pathlib.Path('/app/licenses/sbom.spdx.json').is_file()"

echo "Verified ${IMAGE}: arch=${EXPECTED_ARCH}, user=${IMAGE_USER}, offline restricted healthcheck=ok"
