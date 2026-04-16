FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install uv

WORKDIR /runtime

RUN uv pip install --system \
    numpy \
    pandas \
    requests \
    httpx \
    PyYAML \
    python-frontmatter \
    rich \
    click

CMD ["python", "--version"]
