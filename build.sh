#!/bin/bash
set -e

TAG=${TAG:-latest}
PLATFORM=${PLATFORM:-linux/amd64}

GREEN='\033[0;32m'
NC='\033[0m'

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -t, --tag TAG       Image tag (default: latest)"
    echo "  -p, --platform P    Platform (default: linux/amd64)"
    echo "  -a, --all           Build backend, frontend, sandbox, sandbox runtime, security worker, and AIG scan service"
    echo "  -b, --backend       Build backend image"
    echo "  -f, --frontend      Build frontend image"
    echo "  -s, --sandbox       Build isolated sandbox service image"
    echo "  -r, --runtime       Build local sandbox runtime image"
    echo "  -w, --security-worker Build Agent Security worker image"
    echo "  -g, --aig-scan-service Build fixed AI-Infra-Guard internal service image"
    echo "  --save              Save all runtime images to docker_images/<arch>/ as tar.xz"
    echo "  -h, --help          Show this help"
}

step() {
    echo -e "${GREEN}[BUILD]${NC} $1"
}

pull_image() {
    local image="$1"
    local attempt
    for attempt in 1 2 3 4 5; do
        if docker pull --platform "${PLATFORM}" "$image"; then
            return 0
        fi
        if [ "$attempt" -eq 5 ]; then
            echo "Failed to pull ${image} for ${PLATFORM} after 5 attempts" >&2
            return 1
        fi
        step "Pull failed for ${image} (attempt ${attempt}/5); retrying in $((attempt * 5))s"
        sleep "$((attempt * 5))"
    done
}

build_image() {
    local attempt
    for attempt in 1 2 3; do
        if docker buildx build "$@"; then
            return 0
        fi
        if [ "$attempt" -eq 3 ]; then
            echo "Image build failed after 3 attempts" >&2
            return 1
        fi
        step "Image build failed (attempt ${attempt}/3); retrying in $((attempt * 5))s"
        sleep "$((attempt * 5))"
    done
}

docker_buildx_proxy_args() {
    local args=()
    [[ -n "${http_proxy:-}" ]] && args+=(--build-arg "http_proxy=${http_proxy}" --build-arg "HTTP_PROXY=${http_proxy}")
    [[ -n "${https_proxy:-}" ]] && args+=(--build-arg "https_proxy=${https_proxy}" --build-arg "HTTPS_PROXY=${https_proxy}")
    [[ -n "${all_proxy:-}" ]] && args+=(--build-arg "all_proxy=${all_proxy}" --build-arg "ALL_PROXY=${all_proxy}")
    [[ -n "${BUILD_APT_PROXY:-}" ]] && args+=(--build-arg "APT_PROXY=${BUILD_APT_PROXY}")
    [[ -n "${BUILD_GIT_PROXY:-}" ]] && args+=(--build-arg "GIT_PROXY=${BUILD_GIT_PROXY}")
    [[ -n "${BUILD_GOPROXY:-}" ]] && args+=(--build-arg "GOPROXY=${BUILD_GOPROXY}")
    [[ -n "${BUILD_PYPI_INDEX:-}" ]] && args+=(--build-arg "PYPI_INDEX=${BUILD_PYPI_INDEX}")
    printf '%s\n' "${args[@]}"
}

build_backend() {
    step "Building ${BACKEND_IMAGE}"
    build_image $(docker_buildx_proxy_args) --load -f backend/Dockerfile --platform "${PLATFORM}" -t "${BACKEND_IMAGE}" .
}

build_frontend() {
    step "Building ${FRONTEND_IMAGE}"
    build_image $(docker_buildx_proxy_args) --load -f web/Dockerfile --platform "${PLATFORM}" -t "${FRONTEND_IMAGE}" .
}

build_sandbox() {
    step "Building ${SANDBOX_IMAGE}"
    build_image $(docker_buildx_proxy_args) --load -f services/isolated-sandbox-service/Dockerfile.nsjail --platform "${PLATFORM}" -t "${SANDBOX_IMAGE}" .
}

build_runtime() {
    step "Building ${SANDBOX_RUNTIME_IMAGE}"
    build_image $(docker_buildx_proxy_args) --load -f services/local-sandbox-runtime/Dockerfile --platform "${PLATFORM}" -t "${SANDBOX_RUNTIME_IMAGE}" .
}

build_security_worker() {
    step "Building ${SECURITY_WORKER_IMAGE}"
    build_image $(docker_buildx_proxy_args) --load -f services/agent-security-worker/Dockerfile --platform "${PLATFORM}" -t "${SECURITY_WORKER_IMAGE}" .
}

build_aig_scan_service() {
    step "Building ${AIG_SCAN_SERVICE_IMAGE}"
    build_image $(docker_buildx_proxy_args) --load -f services/aig-scan-service/Dockerfile --platform "${PLATFORM}" -t "${AIG_SCAN_SERVICE_IMAGE}" .
}

arch_dir() {
    case "${PLATFORM}" in
        linux/amd64) echo "x86" ;;
        linux/arm64*|linux/arm/v8|linux/arm) echo "arm" ;;
        *) echo "unknown" ;;
    esac
}

ensure_image() {
    local image="$1"
    local expected_arch="${PLATFORM#linux/}"
    expected_arch="${expected_arch%%/*}"
    if [ "$image" = "nginx:1.27-alpine" ]; then
        step "Pulling ${image} for ${PLATFORM}"
        pull_image "$image"
    fi
    if ! docker image inspect "$image" >/dev/null 2>&1; then
        echo "Missing image: $image"
        exit 1
    fi
    local actual_arch
    actual_arch="$(docker image inspect --format '{{.Architecture}}' "$image")"
    if [ "$actual_arch" != "$expected_arch" ]; then
        echo "Image architecture mismatch: $image is $actual_arch, expected $expected_arch"
        exit 1
    fi
}

save_images() {
    local output_dir="docker_images/$(arch_dir)"
    local output="${output_dir}/agent-manager-images-${TAG}.tar.xz"
    local tmp="${output}.tmp"
    mkdir -p "$output_dir"
    ensure_image "${BACKEND_IMAGE}"
    ensure_image "${FRONTEND_IMAGE}"
    ensure_image "${SANDBOX_IMAGE}"
    ensure_image "${SANDBOX_RUNTIME_IMAGE}"
    ensure_image "${SECURITY_WORKER_IMAGE}"
    ensure_image "${AIG_SCAN_SERVICE_IMAGE}"
    ensure_image "nginx:1.27-alpine"
    step "Saving images to ${output}"
    rm -f "$tmp" "${tmp}.xz" "$output"
    docker image save -o "$tmp" \
        "${BACKEND_IMAGE}" \
        "${FRONTEND_IMAGE}" \
        "${SANDBOX_IMAGE}" \
        "${SANDBOX_RUNTIME_IMAGE}" \
        "${SECURITY_WORKER_IMAGE}" \
        "${AIG_SCAN_SERVICE_IMAGE}" \
        nginx:1.27-alpine
    xz -vf -2 -T 4 "$tmp"
    mv "${tmp}.xz" "$output"
}

BUILD_BACKEND=false
BUILD_FRONTEND=false
BUILD_SANDBOX=false
BUILD_RUNTIME=false
BUILD_SECURITY_WORKER=false
BUILD_AIG_SCAN_SERVICE=false
SAVE_IMAGES=false

if [ $# -eq 0 ]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        -t|--tag)
            TAG="$2"
            shift 2
            ;;
        -p|--platform)
            PLATFORM="$2"
            shift 2
            ;;
        -a|--all)
            BUILD_BACKEND=true
            BUILD_FRONTEND=true
            BUILD_SANDBOX=true
            BUILD_RUNTIME=true
            BUILD_SECURITY_WORKER=true
            BUILD_AIG_SCAN_SERVICE=true
            shift
            ;;
        -b|--backend)
            BUILD_BACKEND=true
            shift
            ;;
        -f|--frontend)
            BUILD_FRONTEND=true
            shift
            ;;
        -s|--sandbox)
            BUILD_SANDBOX=true
            shift
            ;;
        -r|--runtime)
            BUILD_RUNTIME=true
            shift
            ;;
        -w|--security-worker)
            BUILD_SECURITY_WORKER=true
            shift
            ;;
        -g|--aig-scan-service)
            BUILD_AIG_SCAN_SERVICE=true
            shift
            ;;
        --save)
            SAVE_IMAGES=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

BACKEND_IMAGE=agent-manager-backend:${TAG}
FRONTEND_IMAGE=agent-manager-frontend:${TAG}
SANDBOX_IMAGE=agent-manager-sandbox:${TAG}
SANDBOX_RUNTIME_IMAGE=agent-manager-sandbox-runtime:${TAG}
SECURITY_WORKER_IMAGE=agent-manager-security-worker:${TAG}
AIG_SCAN_SERVICE_IMAGE=agent-manager-aig-scan-service:${TAG}

if $BUILD_BACKEND || $BUILD_SANDBOX || $BUILD_RUNTIME || $BUILD_SECURITY_WORKER || $BUILD_AIG_SCAN_SERVICE; then
    step "Pulling python:3.12-slim for ${PLATFORM}"
    pull_image python:3.12-slim
fi
if $BUILD_FRONTEND; then
    step "Pulling frontend base images for ${PLATFORM}"
    pull_image node:22-alpine
    pull_image nginx:1.27-alpine
fi
if $BUILD_SANDBOX; then
    step "Pulling nsjail base images for ${PLATFORM}"
    pull_image buildpack-deps:bookworm
    pull_image debian:bookworm-slim
fi

$BUILD_BACKEND && build_backend
$BUILD_FRONTEND && build_frontend
$BUILD_SANDBOX && build_sandbox
$BUILD_RUNTIME && build_runtime
$BUILD_SECURITY_WORKER && build_security_worker
$BUILD_AIG_SCAN_SERVICE && build_aig_scan_service
$SAVE_IMAGES && save_images

step "Done"
