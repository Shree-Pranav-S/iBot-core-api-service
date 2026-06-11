FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	PORT=8000

WORKDIR /app

COPY pyproject.toml ./
COPY alembic.ini ./
COPY docker-entrypoint.sh ./
COPY src ./src

RUN python -m pip install --upgrade pip \
	&& python -c "import tomllib, pathlib; deps=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')).get('project', {}).get('dependencies', []); pathlib.Path('/tmp/requirements.txt').write_text('\\n'.join(deps) + '\\n', encoding='utf-8')" \
	&& pip install --prefer-binary -r /tmp/requirements.txt \
	&& chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["sh", "docker-entrypoint.sh"]
