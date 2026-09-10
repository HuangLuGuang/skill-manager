# syntax=docker/dockerfile:1.7
ARG GO_BASE=golang:1.23.2-alpine@sha256:9dd2625a1ff2859b8d8b01d8f7822c0f528942fe56cfe7a1e7c38d3b8d72d679
ARG PYTHON_BASE=python:3.12.9-slim-bookworm@sha256:48a11b7ba705fd53bf15248d1f94d36c39549903c5d59edcfa2f3f84126e7b44

FROM --platform=$BUILDPLATFORM ${GO_BASE} AS go-builder
ARG TARGETOS=linux
ARG TARGETARCH
ARG GOPROXY=https://proxy.golang.org
WORKDIR /src
COPY services/aig-scan-service/vendor/ai-infra-guard/go.mod services/aig-scan-service/vendor/ai-infra-guard/go.sum ./
RUN GOPROXY="$GOPROXY" go mod download
COPY services/aig-scan-service/vendor/ai-infra-guard/ ./
RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -trimpath -ldflags="-s -w" -o /out/ai-infra-guard ./cmd/cli && \
    CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -trimpath -ldflags="-s -w" -o /out/agent ./cmd/agent

FROM ${PYTHON_BASE}
ARG UV_VERSION=0.6.10
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEEPEVAL_TELEMETRY_OPT_OUT=YES \
    DEEPTEAM_TELEMETRY_OPT_OUT=YES \
    AIG_RUNTIME_DIR=/opt/aig \
    AIG_UPSTREAM_URL=http://127.0.0.1:18088 \
    AIG_AGENT_BIN=/opt/aig/bin/agent \
    AIG_SERVER_BIN=/opt/aig/bin/ai-infra-guard \
    AIG_WRAPPER_DB=/var/lib/aig-wrapper/jobs.db \
    DB_PATH=/tmp/aig-upstream/tasks.db \
    AIG_API_CHECKER_URL="" \
    HOME=/tmp/aig-home \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_PROJECT_ENVIRONMENT=/opt/aig/AIG-PromptSecurity/.venv \
    VIRTUAL_ENV=/opt/aig/AIG-PromptSecurity/.venv \
    PATH=/opt/aig/AIG-PromptSecurity/.venv/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

LABEL org.opencontainers.image.title="Agent Manager AI-Infra-Guard Scan Service" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/Tencent/AI-Infra-Guard" \
      org.opencontainers.image.version="v4.6.0" \
      org.opencontainers.image.revision="e8931cc68001b66ad024fd87ef07394e9e96524a"

RUN for attempt in 1 2 3; do \
      rm -rf /var/lib/apt/lists/*; \
      if apt-get -o Acquire::Retries=5 -o APT::Update::Error-Mode=any update; then break; fi; \
      if [ "$attempt" -eq 3 ]; then exit 1; fi; \
      sleep "$((attempt * 5))"; \
    done \
    && for attempt in 1 2 3 4 5; do \
      if apt-get -o Acquire::Retries=5 --download-only install -y --no-install-recommends \
        ca-certificates chromium nmap; then break; fi; \
      if [ "$attempt" -eq 5 ]; then exit 1; fi; \
      echo "APT dependency download failed (attempt ${attempt}/5); retrying in $((attempt * 5))s"; \
      sleep "$((attempt * 5))"; \
    done \
    && apt-get --no-download install -y --no-install-recommends ca-certificates chromium nmap \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --no-create-home --uid 10002 --shell /usr/sbin/nologin aigscan

WORKDIR /opt/aig
COPY services/aig-scan-service/vendor/ai-infra-guard/ /opt/aig/
COPY services/agent-security-worker/verify_vendor_tree.py /opt/service/verify_vendor_tree.py
COPY deploy/agent-security/upstreams.lock.json /opt/service/upstreams.lock.json
COPY services/aig-scan-service/requirements.lock /opt/service/requirements.lock
COPY services/aig-scan-service/generate_sbom.py /opt/service/generate_sbom.py

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && python /opt/service/verify_vendor_tree.py \
        --lock /opt/service/upstreams.lock.json \
        --vendor-base /opt/aig \
        --component full-service \
    && cd /opt/aig/AIG-PromptSecurity \
    && UV_CACHE_DIR=/tmp/uv-cache uv sync --frozen --no-dev --no-install-project \
    && UV_CACHE_DIR=/tmp/uv-cache uv pip install \
        --python /opt/aig/AIG-PromptSecurity/.venv/bin/python \
        --require-hashes -r /opt/service/requirements.lock \
    && mkdir -p /opt/service/licenses /var/lib/aig-wrapper /tmp/aig-home /tmp/aig-redteam /tmp/aig-upstream \
    && cp /opt/aig/LICENSE /opt/aig/NOTICE /opt/service/licenses/ \
    && ln -s /tmp/aig-redteam/logs /opt/aig/AIG-PromptSecurity/logs \
    && /opt/aig/AIG-PromptSecurity/.venv/bin/python /opt/service/generate_sbom.py /opt/service/licenses/sbom.spdx.json \
    && rm -rf /tmp/uv-cache /root/.cache \
    && chown -R 10002:10002 /var/lib/aig-wrapper /tmp/aig-home /tmp/aig-redteam /tmp/aig-upstream

COPY services/aig-scan-service/service.py services/aig-scan-service/healthcheck.py /opt/service/
COPY --from=go-builder /out/ai-infra-guard /out/agent /opt/aig/bin/

WORKDIR /opt/service
USER 10002:10002
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=5 \
    CMD ["python", "/opt/service/healthcheck.py"]
ENTRYPOINT ["python", "-m", "uvicorn"]
CMD ["service:app", "--host", "0.0.0.0", "--port", "8093", "--workers", "1", "--no-access-log"]
