FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --index-url "$PYPI_INDEX" uv

# Install SkillSpector CLI for optional security scanning
ARG APT_PROXY
ARG GIT_PROXY
RUN if [ -n "$APT_PROXY" ]; then printf 'Acquire::http::Proxy "%s";\n' "$APT_PROXY" > /etc/apt/apt.conf.d/99build-proxy; fi \
    && for attempt in 1 2 3; do \
      rm -rf /var/lib/apt/lists/*; \
      if apt-get -o Acquire::Retries=5 -o APT::Update::Error-Mode=any update; then break; fi; \
      if [ "$attempt" -eq 3 ]; then exit 1; fi; \
      sleep "$((attempt * 5))"; \
    done \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
      git make build-essential \
    && rm -f /etc/apt/apt.conf.d/99build-proxy \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/tools \
    && cd /app/tools \
    && if [ -n "$GIT_PROXY" ]; then git -c http.proxy="$GIT_PROXY" clone https://github.com/NVIDIA/SkillSpector.git; else git clone https://github.com/NVIDIA/SkillSpector.git; fi \
    && cd SkillSpector \
    && uv venv --python 3.12 .venv \
    && . .venv/bin/activate \
    && PIP_INDEX_URL="$PYPI_INDEX" UV_DEFAULT_INDEX="$PYPI_INDEX" make install

WORKDIR /app

COPY pyproject.toml README.md company-policy.example.yaml ./
COPY agent_manager ./agent_manager
COPY backend ./backend
COPY services/aig-scan-service/vendor/ai-infra-guard/data/eval ./services/aig-scan-service/vendor/ai-infra-guard/data/eval
COPY services/aig-scan-service/vendor/ai-infra-guard/LICENSE services/aig-scan-service/vendor/ai-infra-guard/NOTICE ./services/aig-scan-service/vendor/ai-infra-guard/
COPY deploy/agent-security ./deploy/agent-security
COPY demo/agent-manager-skill-verifier ./demo/agent-manager-skill-verifier
COPY demo/mcp-customer-operations ./demo/mcp-customer-operations

RUN UV_DEFAULT_INDEX="$PYPI_INDEX" uv pip install --system -e ".[scanner,compression]" && \
    UV_DEFAULT_INDEX="$PYPI_INDEX" uv pip install --system \
      sqlalchemy \
      pydantic[email] \
      pydantic-settings \
      python-jose[cryptography] \
      passlib[bcrypt] \
      "bcrypt<4" \
      captcha \
      psutil \
      croniter \
      python-frontmatter

# Pre-download tiktoken encoding files (downloaded from Azure CDN on first use, ~2MB)
ENV TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base'); tiktoken.get_encoding('o200k_base')" 2>&1

# Warm up headroom (triggers any lazy init, uses pre-cached tiktoken files)
RUN python -c "from headroom import compress; compress([{'role':'user','content':'warmup'}], model='gpt-4o', optimize=False)" 2>&1 || true

RUN mkdir -p /app/runtime/data /app/runtime/uploads /app/runtime/sqlite /app/runtime/agent_manager

ENV PYTHONPATH=/app \
    SKILLSPECTOR_BIN=/app/tools/SkillSpector/.venv/bin/skillspector \
    DEBUG=false \
    DATA_DIR=/app/runtime/data \
    UPLOADS_DIR=/app/runtime/uploads \
    SQLITE_PATH=/app/runtime/sqlite/admin_starter.db \
    AGENT_MANAGER_DATA_DIR=/app/runtime/agent_manager \
    TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
