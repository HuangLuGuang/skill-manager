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
    echo "  -a, --all           Build backend, frontend, sandbox, and sandbox runtime"
    echo "  -b, --backend       Build backend image"
    echo "  -f, --frontend      Build frontend image"
    echo "  -s, --sandbox       Build isolated sandbox service image"
    echo "  -r, --runtime       Build local sandbox runtime image"
    echo "  --save              Save all runtime images to docker_images/<arch>/"
    echo "  -h, --help          Show this help"
}

step() {
    echo -e "${GREEN}[BUILD]${NC} $1"
}

build_backend() {
    step "Building ${BACKEND_IMAGE}"
    docker buildx build --load -f backend/Dockerfile --platform "${PLATFORM}" -t "${BACKEND_IMAGE}" .
}

build_frontend() {
    step "Building ${FRONTEND_IMAGE}"
    docker buildx build --load -f web/Dockerfile --platform "${PLATFORM}" -t "${FRONTEND_IMAGE}" .
}

build_sandbox() {
    step "Building ${SANDBOX_IMAGE}"
    docker buildx build --load -f services/isolated-sandbox-service/Dockerfile --platform "${PLATFORM}" -t "${SANDBOX_IMAGE}" .
}

build_runtime() {
    step "Building ${SANDBOX_RUNTIME_IMAGE}"
    docker buildx build --load -f services/local-sandbox-runtime/Dockerfile --platform "${PLATFORM}" -t "${SANDBOX_RUNTIME_IMAGE}" .
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
    if docker image inspect "$image" >/dev/null 2>&1; then
        return
    fi
    if [ "$image" = "nginx:1.27-alpine" ]; then
        step "Pulling ${image}"
        docker pull --platform "${PLATFORM}" "$image"
        return
    fi
    echo "Missing image: $image"
    exit 1
}

save_images() {
    local output_dir="docker_images/$(arch_dir)"
    local output="${output_dir}/agent-manager-images-${TAG}.tar"
    mkdir -p "$output_dir"
    ensure_image "${BACKEND_IMAGE}"
    ensure_image "${FRONTEND_IMAGE}"
    ensure_image "${SANDBOX_IMAGE}"
    ensure_image "${SANDBOX_RUNTIME_IMAGE}"
    ensure_image "nginx:1.27-alpine"
    step "Saving images to ${output}"
    docker image save -o "$output" \
        "${BACKEND_IMAGE}" \
        "${FRONTEND_IMAGE}" \
        "${SANDBOX_IMAGE}" \
        "${SANDBOX_RUNTIME_IMAGE}" \
        nginx:1.27-alpine
}

BUILD_BACKEND=false
BUILD_FRONTEND=false
BUILD_SANDBOX=false
BUILD_RUNTIME=false
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

$BUILD_BACKEND && build_backend
$BUILD_FRONTEND && build_frontend
$BUILD_SANDBOX && build_sandbox
$BUILD_RUNTIME && build_runtime
$SAVE_IMAGES && save_images

step "Done"
