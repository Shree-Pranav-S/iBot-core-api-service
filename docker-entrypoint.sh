#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
exec uvicorn src.api.rest.app:app --host 0.0.0.0 --port ${PORT:-8000}
