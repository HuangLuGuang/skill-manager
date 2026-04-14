FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install uv

WORKDIR /app

COPY services/isolated-sandbox-service/pyproject.toml ./
RUN uv pip install --system \
    fastapi \
    uvicorn \
    "pydantic>=2.6.0" \
    requests \
    httpx \
    PyYAML \
    python-frontmatter \
    rich \
    click

COPY services/isolated-sandbox-service/app.py ./

ENV SANDBOX_SERVICE_BACKEND=subprocess \
    SANDBOX_SERVICE_WORK_ROOT=/tmp/isolated-sandbox-service

EXPOSE 8194

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8194"]
