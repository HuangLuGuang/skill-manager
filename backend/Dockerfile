FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install uv

WORKDIR /app

COPY pyproject.toml README.md company-policy.example.yaml ./
COPY agent_manager ./agent_manager
COPY backend ./backend

RUN uv pip install --system -e ".[scanner,compression]" && \
    uv pip install --system \
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

# Build-time proxy args (set via: docker build --build-arg HTTPS_PROXY=http://10.10.8.66:1081 ...)
ARG HTTPS_PROXY
ARG HTTP_PROXY
ARG ALL_PROXY

# Pre-download all HF models needed by headroom (uses build-time proxy if set)
ENV HF_HOME=/app/.cache/huggingface
RUN export https_proxy=${HTTPS_PROXY} http_proxy=${HTTP_PROXY} all_proxy=${ALL_PROXY} && \
    python -c "\
from huggingface_hub import snapshot_download;\
for model in ['chopratejas/kompress-base', 'answerdotai/ModernBERT-base', 'deepseek-ai/deepseek-llm-7b-base']:\
    snapshot_download(model);\
    print(f'Downloaded {model}')\
" 2>&1
# Warm up headroom so first request doesn't trigger downloads
RUN export https_proxy=${HTTPS_PROXY} http_proxy=${HTTP_PROXY} all_proxy=${ALL_PROXY} && \
    python -c "from headroom import compress; compress([{'role':'user','content':'warmup'}], model='gpt-4o', optimize=False)" 2>&1 || true

# Clear proxy from runtime env (production has no network)
ENV HTTPS_PROXY= HTTP_PROXY= ALL_PROXY= https_proxy= http_proxy= all_proxy=

RUN mkdir -p /app/runtime/data /app/runtime/uploads /app/runtime/sqlite /app/runtime/agent_manager

ENV PYTHONPATH=/app \
    DEBUG=false \
    DATA_DIR=/app/runtime/data \
    UPLOADS_DIR=/app/runtime/uploads \
    SQLITE_PATH=/app/runtime/sqlite/admin_starter.db \
    AGENT_MANAGER_DATA_DIR=/app/runtime/agent_manager \
    HF_HOME=/app/.cache/huggingface \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    TRANSFORMERS_VERBOSITY=error

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
