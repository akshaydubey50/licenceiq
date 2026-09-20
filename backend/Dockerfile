FROM python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/workspace/backend/.venv/bin:${PATH}"

WORKDIR /workspace/backend

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir "uv>=0.6,<1" \
    && uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
COPY docker-entrypoint.sh ./
RUN groupadd --gid 10001 licenceiq \
    && useradd --uid 10001 --gid licenceiq --create-home --shell /usr/sbin/nologin licenceiq \
    && chmod 0555 docker-entrypoint.sh scripts/check_openai_runtime.py \
    && chown -R licenceiq:licenceiq /workspace/backend

EXPOSE 8000

USER licenceiq

CMD ["./docker-entrypoint.sh"]
