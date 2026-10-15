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
REUSE_IMAGES=false
SOURCE_DIR=""
SOURCE_MODE="git_clone"
SOURCE_COMMIT=""
SOURCE_BRANCH=""
SOURCE_DIRTY=false

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
    echo "  --source-dir DIR     Package the current Git worktree instead of cloning a branch"
    echo "                       (copies tracked and unignored untracked files; ignored files stay out)"
    echo "  -c, --client-releases DIR  Desktop release feed downloaded from CI"
    echo "  --reuse-images      Package already-built images without rebuilding"
    echo "  -h, --help           Show help"
    echo ""
    echo "Examples:"
    echo "  $0 -v v1.0.0 -p linux/amd64"
    echo "  $0 -v v1.0.0 -p linux/arm64"
    echo "  $0 -v v1.0.0 -p linux/arm64 --source-dir ."
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
        --source-dir) require_value "$1" "${2:-}"; SOURCE_DIR="$2"; shift 2 ;;
        -c|--client-releases) require_value "$1" "${2:-}"; CLIENT_RELEASES="$2"; shift 2 ;;
        --reuse-images) REUSE_IMAGES=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) err "Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [ -z "$VERSION" ]; then
    VERSION="v$(date +%Y%m%d)"
fi

case "$WORK_DIR" in
    /*) ;;
    *) WORK_DIR="${PWD}/${WORK_DIR}" ;;
esac
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

ARCH="$(arch_name)"
if [ "$ARCH" = "unknown" ]; then
    err "Unsupported platform: ${PLATFORM}"
    exit 1
fi

ARCHIVE_VERSION="$VERSION"
if [ "$ARCH" = "arm" ]; then
    ARCHIVE_VERSION="${VERSION%_arm}"
fi
ARCHIVE_NAME="agent-manager_${ARCHIVE_VERSION}_${ARCH}.tar.gz"
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
DOCKER_INSTALLER="$(cd "$(dirname "$DOCKER_INSTALLER")" && pwd)/$(basename "$DOCKER_INSTALLER")"
if [ -n "$CLIENT_RELEASES" ]; then
    if [ ! -d "$CLIENT_RELEASES" ]; then
        err "Client release directory not found: ${CLIENT_RELEASES}"
        exit 1
    fi
    CLIENT_RELEASES="$(cd "$CLIENT_RELEASES" && pwd)"
fi
if [ -n "$SOURCE_DIR" ]; then
    if [ ! -d "$SOURCE_DIR" ]; then
        err "Source directory not found: ${SOURCE_DIR}"
        exit 1
    fi
    SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
    if ! git -C "$SOURCE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        err "Source directory is not a Git worktree: ${SOURCE_DIR}"
        exit 1
    fi
    if [ "$SOURCE_DIR" = "$WORK_DIR" ]; then
        err "Source directory and work directory must be different"
        exit 1
    fi
    if ! SOURCE_COMMIT="$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null)"; then
        err "Source directory must have a Git commit"
        exit 1
    fi
    SOURCE_MODE="worktree"
    SOURCE_BRANCH="$(git -C "$SOURCE_DIR" branch --show-current)"
    if [ -n "$(git -C "$SOURCE_DIR" status --porcelain)" ]; then
        SOURCE_DIRTY=true
    fi
fi

log "Cleaning work directory..."
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"
mkdir -p "$OUTPUT_DIR"

if [ -n "$SOURCE_DIR" ]; then
    log "Copying tracked and unignored files from ${SOURCE_DIR}..."
    while IFS= read -r -d '' source_path; do
        if [ -e "$SOURCE_DIR/$source_path" ] || [ -L "$SOURCE_DIR/$source_path" ]; then
            mkdir -p "$WORK_DIR/$(dirname "$source_path")"
            cp -pP "$SOURCE_DIR/$source_path" "$WORK_DIR/$source_path"
        fi
    done < <(git -C "$SOURCE_DIR" ls-files --cached --others --exclude-standard -z)
else
    log "Cloning ${BRANCH}..."
    git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$WORK_DIR"
    SOURCE_COMMIT="$(git -C "$WORK_DIR" rev-parse HEAD)"
    SOURCE_BRANCH="$(git -C "$WORK_DIR" branch --show-current)"
fi

cd "$WORK_DIR"

log "Writing release provenance..."
PROVENANCE_VERSION="$VERSION" \
PROVENANCE_PLATFORM="$PLATFORM" \
PROVENANCE_ARCH="${PLATFORM#linux/}" \
PROVENANCE_ARCHIVE_LAYOUT="$ARCH" \
PROVENANCE_SOURCE_MODE="$SOURCE_MODE" \
PROVENANCE_COMMIT="$SOURCE_COMMIT" \
PROVENANCE_BRANCH="$SOURCE_BRANCH" \
PROVENANCE_DIRTY="$SOURCE_DIRTY" \
python3 - <<'PY'
import json
import os
from datetime import datetime, timezone

payload = {
    "schema": "agent-manager-release-provenance@1",
    "version": os.environ["PROVENANCE_VERSION"],
    "platform": os.environ["PROVENANCE_PLATFORM"],
    "architecture": os.environ["PROVENANCE_ARCH"],
    "archive_layout": os.environ["PROVENANCE_ARCHIVE_LAYOUT"],
    "source_mode": os.environ["PROVENANCE_SOURCE_MODE"],
    "git_commit": os.environ["PROVENANCE_COMMIT"],
    "git_branch": os.environ["PROVENANCE_BRANCH"],
    "worktree_dirty": os.environ["PROVENANCE_DIRTY"] == "true",
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
with open("release-provenance.json", "w", encoding="utf-8") as stream:
    json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
    stream.write("\n")
PY

if [ "$REUSE_IMAGES" = true ]; then
    log "Saving existing Docker images..."
    bash build.sh -t "$VERSION" -p "$PLATFORM" --save
else
    log "Building and saving Docker images..."
    bash build.sh -t "$VERSION" -p "$PLATFORM" --all --save
fi
IMAGE_DIR="docker_images/${ARCH}"
IMAGE_TAR="${IMAGE_DIR}/agent-manager-images-${VERSION}.tar"
IMAGE_XZ="${IMAGE_TAR}.xz"
if [ -f "$IMAGE_TAR" ] && [ ! -f "$IMAGE_XZ" ]; then
    log "Compressing Docker image tar to xz: ${IMAGE_XZ}"
    xz -vf -2 -T 4 "$IMAGE_TAR"
fi

test -s "$IMAGE_XZ"

log "Staging deployment files..."
WORK_PARENT="$(dirname "$WORK_DIR")"
PACKAGE_PARENT="$(mktemp -d "${WORK_PARENT}/agent-manager-package.XXXXXX")"
trap 'rm -rf "$PACKAGE_PARENT"' EXIT
PACKAGE_DIR="${PACKAGE_PARENT}/agent-manager"
mkdir -p "$PACKAGE_DIR/$IMAGE_DIR" "$PACKAGE_DIR/installers" \
    "$PACKAGE_DIR/deploy/nginx" "$PACKAGE_DIR/docs" "$PACKAGE_DIR/scanner/releases"
cp docker-compose.yaml .env.example release-provenance.json "$PACKAGE_DIR/"
PACKAGE_COMPOSE="$PACKAGE_DIR/docker-compose.yaml" PACKAGE_VERSION="$VERSION" python3 - <<'PY'
import os
from pathlib import Path

compose = Path(os.environ["PACKAGE_COMPOSE"])
compose.write_text(compose.read_text().replace("${TAG:-latest}", os.environ["PACKAGE_VERSION"]))
PY
cp start.sh upgrade.sh "$PACKAGE_DIR/"
chmod +x "$PACKAGE_DIR/start.sh" "$PACKAGE_DIR/upgrade.sh"
cp deploy/offline.py "$PACKAGE_DIR/deploy/"
cp deploy/nginx/default.conf "$PACKAGE_DIR/deploy/nginx/"
cp docs/offline-deployment.md docs/docker-deployment.md docs/license.md "$PACKAGE_DIR/docs/"
mv "$IMAGE_XZ" "$PACKAGE_DIR/$IMAGE_DIR/"
cp "$DOCKER_INSTALLER" "$PACKAGE_DIR/installers/docker-installer-28.5.2-x86-arm.tar.gz"
if [ -n "$CLIENT_RELEASES" ]; then
    log "Copying desktop client release feed..."
    cp -R "$CLIENT_RELEASES"/. "$PACKAGE_DIR/scanner/releases/"
fi

log "Creating release archive..."
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE_PATH" -C "$PACKAGE_PARENT" agent-manager
rm -rf "$PACKAGE_PARENT"
trap - EXIT

log "Archive created: ${ARCHIVE_PATH}"
log "Archive size: $(du -h "$ARCHIVE_PATH" | cut -f1)"

log "Cleaning work directory..."
rm -rf "$WORK_DIR"

log "Done"
