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

# Pre-download tiktoken encoding files (downloaded from Azure CDN on first use, ~2MB)
ENV TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base'); tiktoken.get_encoding('o200k_base')" 2>&1

# Warm up headroom (triggers any lazy init, uses pre-cached tiktoken files)
RUN python -c "from headroom import compress; compress([{'role':'user','content':'warmup'}], model='gpt-4o', optimize=False)" 2>&1 || true

RUN mkdir -p /app/runtime/data /app/runtime/uploads /app/runtime/sqlite /app/runtime/agent_manager

ENV PYTHONPATH=/app \
    DEBUG=false \
    DATA_DIR=/app/runtime/data \
    UPLOADS_DIR=/app/runtime/uploads \
    SQLITE_PATH=/app/runtime/sqlite/admin_starter.db \
    AGENT_MANAGER_DATA_DIR=/app/runtime/agent_manager \
    TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
