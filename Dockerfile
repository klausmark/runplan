# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/runplan

RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .


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
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/users', timeout=2)"]

CMD ["runplan", "serve", "--host", "0.0.0.0", "--port", "8000"]
