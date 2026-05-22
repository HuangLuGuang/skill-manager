FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install uv

WORKDIR /app

COPY pyproject.toml README.md company-policy.example.yaml ./
COPY agent_manager ./agent_manager
COPY backend ./backend

RUN uv pip install --system -e . && \
    uv pip install --system \
      cisco-ai-skill-scanner \
      fastapi \
      httpx \
      uvicorn \
      sqlalchemy \
      pydantic[email] \
      pydantic-settings \
      python-dotenv \
      python-multipart \
      python-jose[cryptography] \
      passlib[bcrypt] \
      "bcrypt<4" \
      captcha \
      psutil \
      croniter \
      PyYAML \
      python-frontmatter

RUN mkdir -p /app/runtime/data /app/runtime/uploads /app/runtime/sqlite /app/runtime/agent_manager

ENV PYTHONPATH=/app \
    DEBUG=false \
    DATA_DIR=/app/runtime/data \
    UPLOADS_DIR=/app/runtime/uploads \
    SQLITE_PATH=/app/runtime/sqlite/admin_starter.db \
    AGENT_MANAGER_DATA_DIR=/app/runtime/agent_manager

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
