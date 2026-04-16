#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${1:-}" != "" ]]; then
  VERSION="$1"
else
  DATE_PART="$(date +%Y.%m.%d)"
  GIT_PART="$(git rev-parse --short HEAD 2>/dev/null || date +%H%M%S)"
  VERSION="${DATE_PART}-${GIT_PART}"
fi

OUT_DIR="releases/${VERSION}"
mkdir -p "$OUT_DIR"

build_binary() {
  local goos="$1"
  local goarch="$2"
  local edition="$3"
  local package_path="$4"
  local suffix="${goos}-${goarch}"
  local ext=""
  if [[ "$goos" == "windows" ]]; then
    ext=".exe"
  fi
  local name="skill-scanner-${edition}-${suffix}${ext}"
  echo "building ${name}"
  GOCACHE="${GOCACHE:-/tmp/skill-manager-go-cache}" GOOS="$goos" GOARCH="$goarch" go build -o "${OUT_DIR}/${name}" "$package_path"
  cp "${OUT_DIR}/${name}" "releases/${name}"
}

build_gui_binary() {
  local goos="$1"
  local goarch="$2"
  local suffix="${goos}-${goarch}"
  local ext=""
  if [[ "$goos" == "windows" ]]; then
    ext=".exe"
  fi
  local name="skill-scanner-gui-${suffix}${ext}"
  echo "building ${name}"
  if GOCACHE="${GOCACHE:-/tmp/skill-manager-go-cache}" CGO_ENABLED=1 GOOS="$goos" GOARCH="$goarch" go build -o "${OUT_DIR}/${name}" ./cmd/skill-scanner-gui; then
    cp "${OUT_DIR}/${name}" "releases/${name}"
  else
    echo "warning: failed to build ${name}; build it on the target platform or install the required GUI toolchain" >&2
  fi
}

build_binary darwin arm64 cli ./cmd/skill-scanner
build_binary darwin amd64 cli ./cmd/skill-scanner
build_binary linux amd64 cli ./cmd/skill-scanner
build_binary linux arm64 cli ./cmd/skill-scanner

if [[ "${BUILD_WINDOWS_CLI:-0}" == "1" ]]; then
  build_binary windows amd64 cli ./cmd/skill-scanner
fi

# Fyne GUI depends on platform GUI toolchains. By default, build only the current macOS host GUI.
if [[ "$(go env GOOS)" == "darwin" ]]; then
  build_gui_binary darwin "$(go env GOARCH)"
  if [[ "${BUILD_DARWIN_AMD64_GUI:-1}" == "1" && "$(go env GOARCH)" == "arm64" ]]; then
    build_gui_binary darwin amd64
  fi
fi

if [[ "${BUILD_LINUX_GUI:-0}" == "1" ]]; then
  build_gui_binary linux amd64
  build_gui_binary linux arm64
fi

if [[ "${BUILD_WINDOWS_GUI:-0}" == "1" ]]; then
  build_gui_binary windows amd64
fi

cat > "${OUT_DIR}/manifest.txt" <<EOF
version=${VERSION}
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
git_commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)
EOF

echo "release directory: ${ROOT_DIR}/${OUT_DIR}"
