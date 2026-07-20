#!/bin/bash
set -euo pipefail

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo master)"
VERSION=""
PLATFORM="linux/amd64"
DOCKER_INSTALLER="/home/ubuntu/docker-installer-28.5.2-x86-arm.tar.gz"
WORK_DIR="/tmp/agent-manager"
OUTPUT_DIR="${PWD}"
REPO_URL="git@git.dev-rs.com:agnitio/skill-manager.git"
CLIENT_RELEASES=""

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "  -v, --version VER    Version tag (default: vYYYYMMDD)"
    echo "  -b, --branch BRANCH  Git branch to clone (default: current branch)"
    echo "  -p, --platform PLAT  linux/amd64 or linux/arm64 (default: linux/amd64)"
    echo "  -i, --installer FILE Docker installer tar.gz"
    echo "                       (default: /home/ubuntu/docker-installer-28.5.2-x86-arm.tar.gz)"
    echo "  -o, --output DIR     Output directory (default: current dir)"
    echo "  -w, --work-dir DIR   Working directory (default: /tmp/agent-manager)"
    echo "  -r, --repo URL       Git repo URL (default: ${REPO_URL})"
    echo "  -c, --client-releases DIR  Desktop release feed downloaded from CI"
    echo "  -h, --help           Show help"
    echo ""
    echo "Examples:"
    echo "  $0 -v v1.0.0 -p linux/amd64"
    echo "  $0 -v v1.0.0 -p linux/arm64"
    echo "  $0 -v v1.0.0 -p linux/amd64 -c /path/to/agent-manager-client-update-feed"
}

log() { echo -e "${GREEN}[INFO]${NC}  $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; }

require_value() {
    if [ -z "${2:-}" ]; then
        err "$1 requires a value"
        usage
        exit 1
    fi
}

arch_name() {
    case "$PLATFORM" in
        linux/amd64) echo "x86" ;;
        linux/arm64*|linux/arm/v8|linux/arm) echo "arm" ;;
        *) echo "unknown" ;;
    esac
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--version) require_value "$1" "${2:-}"; VERSION="$2"; shift 2 ;;
        -b|--branch) require_value "$1" "${2:-}"; BRANCH="$2"; shift 2 ;;
        -p|--platform) require_value "$1" "${2:-}"; PLATFORM="$2"; shift 2 ;;
        -i|--installer) require_value "$1" "${2:-}"; DOCKER_INSTALLER="$2"; shift 2 ;;
        -o|--output) require_value "$1" "${2:-}"; OUTPUT_DIR="$2"; shift 2 ;;
        -w|--work-dir) require_value "$1" "${2:-}"; WORK_DIR="$2"; shift 2 ;;
        -r|--repo) require_value "$1" "${2:-}"; REPO_URL="$2"; shift 2 ;;
        -c|--client-releases) require_value "$1" "${2:-}"; CLIENT_RELEASES="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) err "Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [ -z "$VERSION" ]; then
    VERSION="v$(date +%Y%m%d)"
fi

ARCH="$(arch_name)"
if [ "$ARCH" = "unknown" ]; then
    err "Unsupported platform: ${PLATFORM}"
    exit 1
fi

ARCHIVE_NAME="agent-manager_${VERSION}_${ARCH}.tar.gz"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"

echo ""
echo "=========================================="
echo "  Agent Manager Release Packaging"
echo "=========================================="
echo "  Version:   ${VERSION}"
echo "  Branch:    ${BRANCH}"
echo "  Platform:  ${PLATFORM}"
echo "  Arch:      ${ARCH}"
echo "  Installer: ${DOCKER_INSTALLER}"
echo "  Archive:   ${ARCHIVE_PATH}"
echo "=========================================="
echo ""

if [ ! -f "$DOCKER_INSTALLER" ]; then
    err "Docker installer not found: ${DOCKER_INSTALLER}"
    exit 1
fi
if [ -n "$CLIENT_RELEASES" ]; then
    if [ ! -d "$CLIENT_RELEASES" ]; then
        err "Client release directory not found: ${CLIENT_RELEASES}"
        exit 1
    fi
    CLIENT_RELEASES="$(cd "$CLIENT_RELEASES" && pwd)"
fi

log "Cleaning work directory..."
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"
mkdir -p "$OUTPUT_DIR"

log "Cloning ${BRANCH}..."
git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$WORK_DIR"

cd "$WORK_DIR"

log "Copying docker installer..."
mkdir -p installers
cp "$DOCKER_INSTALLER" "installers/docker-installer-28.5.2-x86-arm.tar.gz"

if [ -n "$CLIENT_RELEASES" ]; then
    log "Copying desktop client releases..."
    cp -R "$CLIENT_RELEASES"/. scanner/releases/
fi

log "Building and saving Docker images..."
bash build.sh -t "$VERSION" -p "$PLATFORM" --all --save
IMAGE_DIR="docker_images/${ARCH}"
IMAGE_TAR="${IMAGE_DIR}/agent-manager-images-${VERSION}.tar"
IMAGE_XZ="${IMAGE_TAR}.xz"
if [ -f "$IMAGE_TAR" ] && [ ! -f "$IMAGE_XZ" ]; then
    log "Compressing Docker image tar to xz: ${IMAGE_XZ}"
    xz -vf -2 -T 4 "$IMAGE_TAR"
fi

log "Creating release archive..."
rm -rf .git
WORK_PARENT="$(dirname "$WORK_DIR")"
WORK_BASE="$(basename "$WORK_DIR")"
tar -czf "$ARCHIVE_PATH" -C "$WORK_PARENT" "$WORK_BASE"

log "Archive created: ${ARCHIVE_PATH}"
log "Archive size: $(du -h "$ARCHIVE_PATH" | cut -f1)"

log "Cleaning work directory..."
rm -rf "$WORK_DIR"

log "Done"
