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
    -c "import os,pathlib,sys,tempfile; sys.path.insert(0, '/app'); os.chdir(tempfile.mkdtemp(dir='/tmp')); import worker; import mcp_executor; from mcp_scan.agent.agent import Agent; from mcp_scan.redteam.orchestrator import RedTeamOrchestrator; from mcp_scan.utils.prompt_manager import prompt_manager; assert prompt_manager.load_template('agents/code_audit'); assert prompt_manager.load_template('agents/dynamic/general_analyzing_prompt_template'); assert worker._mcp_adapter._upstream_description_contract(); worker._touch_health(); assert worker._healthcheck() == 0; assert pathlib.Path('/app/licenses/LICENSE').is_file(); assert pathlib.Path('/app/licenses/NOTICE').is_file(); assert pathlib.Path('/app/licenses/sbom.spdx.json').is_file()"

echo "Verified ${IMAGE}: arch=${EXPECTED_ARCH}, user=${IMAGE_USER}, offline restricted healthcheck=ok"
