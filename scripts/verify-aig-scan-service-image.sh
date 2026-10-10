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
    *) echo "Unsupported architecture: ${EXPECTED_ARCH}" >&2; exit 2 ;;
esac

ACTUAL_ARCH="$(docker image inspect --format '{{.Architecture}}' "$IMAGE")"
test "$ACTUAL_ARCH" = "$EXPECTED_ARCH"
test "$(docker image inspect --format '{{.Config.User}}' "$IMAGE")" = "10002:10002"
test "$(docker image inspect --format '{{json .Config.Healthcheck.Test}}' "$IMAGE")" = '["CMD","python","/opt/service/healthcheck.py"]'
test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE")" = "e8931cc68001b66ad024fd87ef07394e9e96524a"

HEALTH_TIMEOUT=5s
HEALTH_ATTEMPTS=18
if [ "$EXPECTED_ARCH" = "arm64" ]; then
    HEALTH_TIMEOUT=30s
    HEALTH_ATTEMPTS=36
fi

SUFFIX="${EXPECTED_ARCH}-$$"
CONTAINER="aig-scan-verify-${SUFFIX}"
VOLUME="aig-scan-verify-${SUFFIX}"
cleanup() {
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    docker volume rm "$VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker volume create "$VOLUME" >/dev/null
docker run -d --name "$CONTAINER" \
    --platform "linux/${EXPECTED_ARCH}" \
    --network none \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=512m \
    --mount "type=volume,src=${VOLUME},dst=/var/lib/aig-wrapper" \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --pids-limit 256 \
    --memory 2g \
    --cpus 2 \
    --health-timeout "$HEALTH_TIMEOUT" \
    -e AIG_WRAPPER_TOKEN=test-only-aig-wrapper-auth-value \
    "$IMAGE" >/dev/null

for _ in $(seq 1 "$HEALTH_ATTEMPTS"); do
    STATE="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$CONTAINER")"
    [ "$STATE" = "running healthy" ] && break
    case "$STATE" in exited*|dead*) docker logs --tail 100 "$CONTAINER" >&2; exit 1 ;; esac
    sleep 5
done
test "$(docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' "$CONTAINER")" = "running healthy"

docker exec "$CONTAINER" python -c "import json,pathlib; d=json.loads(pathlib.Path('/opt/service/licenses/sbom.spdx.json').read_text()); assert pathlib.Path('/opt/service/licenses/LICENSE').is_file(); assert pathlib.Path('/opt/service/licenses/NOTICE').is_file(); assert any(p['name']=='AI-Infra-Guard' and p['versionInfo'].startswith('v4.6.0+') for p in d['packages'])"
docker exec "$CONTAINER" sh -c 'cd /opt/aig/AIG-PromptSecurity && uv run --no-project python -c "import deepteam; print(deepteam.__name__)"' | grep -q '^deepteam$'
BEFORE_PID="$(docker top "$CONTAINER" -eo pid,comm | awk '$2=="agent" {print $1}')"
docker exec "$CONTAINER" python -c 'import json,os,urllib.request; h={"Authorization":"Bearer "+os.environ["AIG_WRAPPER_TOKEN"],"Content-Type":"application/json","Idempotency-Key":"image-cancel-verification"}; p={"task_type":"ai_infra_scan","content":{"target":["https://8.8.8.8"],"headers":{},"timeout":30,"model":{"model":"test-evaluator","token":"test-only-short-lived","base_url":"https://models.example/v1","limit":1},"network_policy":{"expected_ips":["8.8.8.8"],"allowed_cidrs":[],"policy_allowed_cidrs":[],"allow_http":False}}}; sid=json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8093/v1/tasks",data=json.dumps(p).encode(),headers=h,method="POST"),timeout=5))["session_id"]; body=json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:8093/v1/tasks/{sid}/cancel",data=b"{}",headers=h,method="POST"),timeout=10)); assert body["execution_stopped"] is True'
sleep 3
AFTER_PID="$(docker top "$CONTAINER" -eo pid,comm | awk '$2=="agent" {print $1}')"
test -n "$BEFORE_PID"
test -n "$AFTER_PID"
test "$BEFORE_PID" != "$AFTER_PID"

echo "Verified ${IMAGE}: arch=${EXPECTED_ARCH}, nonroot/read-only health=ok, process-group cancellation=ok"
