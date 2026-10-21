# Isolated chart runner (ASI05). Only the `chart` dependency group and src/chart_runner: no app code, no
# Azure SDKs, no credentials. Locally Compose runs it with no network on a Unix socket; on Azure it is the
# Dynamic Sessions custom-container image (built for linux/amd64 in ACR by the postprovision hook).
FROM docker.io/library/python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

COPY --from=ghcr.io/astral-sh/uv:0.9.28@sha256:59240a65d6b57e6c507429b45f01b8f2c7c0bbeee0fb697c41a39c6a8e3a4cfb /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# ASI04: exact versions and hashes from uv.lock, chart group only.
COPY pyproject.toml uv.lock README.md ./
RUN uv export --frozen --only-group chart --no-emit-project -o /tmp/requirements.txt \
    && uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python --require-hashes --no-deps -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt pyproject.toml uv.lock README.md \
    && rm /usr/local/bin/uv

COPY src/chart_runner ./chart_runner

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app

# Font cache built once and read-only at runtime, so a fresh worker per job starts quickly.
RUN MPLCONFIGDIR=/app/mplconfig python -c "import matplotlib.pyplot" \
    && chmod -R a+rX /app/mplconfig

USER 10001
EXPOSE 8080
CMD ["python", "-m", "chart_runner", "--port", "8080"]
