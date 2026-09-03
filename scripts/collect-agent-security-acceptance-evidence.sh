#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR=""
RUN_REPO_REGRESSION=false
RUN_RUNTIME_CHECK=false
WORKER_IMAGE=""
WORKER_ARCH=""
COMPOSE_PROJECT=""

usage() {
  echo "Usage: $0 --output-dir /absolute/path [--repo-regression] [--runtime-check] [--compose-project NAME] [--worker-image IMAGE --worker-arch amd64|arm64]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --repo-regression) RUN_REPO_REGRESSION=true; shift ;;
    --runtime-check) RUN_RUNTIME_CHECK=true; shift ;;
    --worker-image) WORKER_IMAGE="${2:-}"; shift 2 ;;
    --worker-arch) WORKER_ARCH="${2:-}"; shift 2 ;;
    --compose-project) COMPOSE_PROJECT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$OUTPUT_DIR" || "$OUTPUT_DIR" != /* ]]; then
  echo "--output-dir must be an explicit absolute path" >&2
  exit 2
fi
if [[ -e "$OUTPUT_DIR" ]] && [[ -n "$(find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  echo "Refusing to overwrite non-empty evidence directory: $OUTPUT_DIR" >&2
  exit 2
fi
if [[ -n "$WORKER_IMAGE" || -n "$WORKER_ARCH" ]]; then
  if [[ -z "$WORKER_IMAGE" || ! "$WORKER_ARCH" =~ ^(amd64|arm64)$ ]]; then
    echo "--worker-image and --worker-arch amd64|arm64 must be provided together" >&2
    exit 2
  fi
fi
if [[ -z "$COMPOSE_PROJECT" ]]; then
  COMPOSE_PROJECT="$(basename "$REPO_DIR" | tr '[:upper:]' '[:lower:]')"
fi
if [[ ! "$COMPOSE_PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  echo "--compose-project must use lowercase letters, digits, underscores, or hyphens" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
cd "$REPO_DIR"

{
  echo "captured_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "os=$(uname -s)"
  echo "architecture=$(uname -m)"
  echo "kernel=$(uname -r)"
  docker version --format 'docker_client={{.Client.Version}} docker_server={{.Server.Version}}'
  docker compose version
} >"$OUTPUT_DIR/environment.txt"

GIT_TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ "$GIT_TOP" = "$REPO_DIR" ]]; then
  SOURCE_KIND="git_worktree"
  {
    echo "source=git_worktree"
    echo "branch=$(git branch --show-current)"
    echo "commit=$(git rev-parse HEAD)"
    echo "worktree_status:"
    git status --short
  } >"$OUTPUT_DIR/git-state.txt"
elif [[ -f release-provenance.json ]]; then
  SOURCE_KIND="release_provenance"
  {
    echo "source=release_provenance"
    python3 -m json.tool release-provenance.json
  } >"$OUTPUT_DIR/git-state.txt"
  cp release-provenance.json "$OUTPUT_DIR/release-provenance.json"
else
  echo "Neither a Git worktree nor release-provenance.json is available" >&2
  exit 1
fi

COMPOSE=(docker compose --env-file /dev/null --profile agent-security)
"${COMPOSE[@]}" config --no-env-resolution --quiet
{
  echo "services:"
  "${COMPOSE[@]}" config --no-env-resolution --services
  echo "profiles:"
  "${COMPOSE[@]}" config --no-env-resolution --profiles
  echo "images:"
  "${COMPOSE[@]}" config --no-env-resolution --images
} >"$OUTPUT_DIR/compose-config.txt"
docker ps --all \
  --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
  --format '{{json .}}' >"$OUTPUT_DIR/compose-ps.json"

if [[ "$RUN_REPO_REGRESSION" == true ]]; then
  uv run pytest -q 2>&1 | tee "$OUTPUT_DIR/backend-tests.log"
  (
    if [[ -s "${NVM_DIR:-${HOME}/.nvm}/nvm.sh" ]]; then
      source "${NVM_DIR:-${HOME}/.nvm}/nvm.sh"
      nvm use 22.21.1 >/dev/null
    fi
    cd web
    node --version
    npm run test:docs-search
    npm run test:i18n
    npm run test:features
    npm run test:agent-security-ui
    npm run test:runtime-trace-ui
  ) 2>&1 | tee "$OUTPUT_DIR/frontend-tests.log"
  (
    if [[ -s "${NVM_DIR:-${HOME}/.nvm}/nvm.sh" ]]; then
      source "${NVM_DIR:-${HOME}/.nvm}/nvm.sh"
      nvm use 22.21.1 >/dev/null
    fi
    cd web
    npm run build
  ) 2>&1 | tee "$OUTPUT_DIR/frontend-build.log"
  if [[ "$SOURCE_KIND" = "git_worktree" ]]; then
    git diff --check >"$OUTPUT_DIR/source-cleanliness-check.txt" 2>&1
  else
    PROVENANCE_VERSION="$(python3 -c 'import json; print(json.load(open("release-provenance.json", encoding="utf-8"))["version"])')"
    PROVENANCE_COMMIT="$(python3 -c 'import json; print(json.load(open("release-provenance.json", encoding="utf-8"))["git_commit"])')"
    PROVENANCE_PLATFORM="$(python3 -c 'import json; print(json.load(open("release-provenance.json", encoding="utf-8"))["platform"])')"
    python3 scripts/verify-agent-manager-release-provenance.py \
      --file release-provenance.json \
      --version "$PROVENANCE_VERSION" \
      --commit "$PROVENANCE_COMMIT" \
      --platform "$PROVENANCE_PLATFORM" \
      --require-clean-clone \
      >"$OUTPUT_DIR/source-cleanliness-check.txt" 2>&1
  fi
fi

if [[ "$RUN_RUNTIME_CHECK" == true ]]; then
  REQUIRED_SERVICES=(backend frontend sandbox nginx agent-security-worker aig-scan-service)
  RUNNING_SERVICES="$(docker ps \
    --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
    --format '{{.Label "com.docker.compose.service"}}')"
  for service in "${REQUIRED_SERVICES[@]}"; do
    if ! grep -Fxq "$service" <<<"$RUNNING_SERVICES"; then
      echo "Required service is not running: $service" >&2
      exit 1
    fi
  done
  docker ps \
    --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
    --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' >"$OUTPUT_DIR/runtime-status.txt"
fi

if [[ -n "$WORKER_IMAGE" ]]; then
  ./scripts/verify-agent-security-worker-image.sh "$WORKER_IMAGE" "$WORKER_ARCH" 2>&1 \
    | tee "$OUTPUT_DIR/worker-image-gate.log"
fi

(
  cd "$OUTPUT_DIR"
  find . -type f ! -name manifest.sha256 -print | LC_ALL=C sort | while IFS= read -r file; do
    shasum -a 256 "$file"
  done >manifest.sha256
)

echo "Evidence collected in: $OUTPUT_DIR"
