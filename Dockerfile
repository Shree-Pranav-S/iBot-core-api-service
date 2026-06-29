FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	PORT=8000

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT="/opt/venv"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY docker-entrypoint.sh ./
COPY src ./src

RUN chmod +x docker-entrypoint.sh \
	&& useradd --create-home --uid 10001 appuser \
	&& chown -R appuser:appuser /app

ENV PATH="/opt/venv/bin:$PATH"
USER appuser

EXPOSE 8000

ENTRYPOINT ["sh", "docker-entrypoint.sh"]
