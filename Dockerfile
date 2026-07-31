# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/runplan \
    UV_PYTHON_DOWNLOADS=0 \
    PATH=/opt/runplan/bin:$PATH

WORKDIR /build

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project --no-editable

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


FROM python:3.13-slim AS runtime

ENV HOME=/data \
    PATH=/opt/runplan/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    RUNPLAN_PROGRAM_DIR=/data/programs \
    RUNPLAN_USERS_FILE=/data/config/users.toml

RUN groupadd --system --gid 10001 runplan \
    && useradd --system --uid 10001 --gid runplan --home-dir /data runplan \
    && mkdir -p /data/config /data/programs \
    && chown -R runplan:runplan /data

COPY --from=builder /opt/runplan /opt/runplan

USER runplan
WORKDIR /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]

CMD ["runplan", "serve", "--host", "0.0.0.0", "--port", "8000"]
