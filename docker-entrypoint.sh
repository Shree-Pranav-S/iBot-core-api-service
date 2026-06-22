#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
if [ "$APP_ENV" = "development" ]; then
    exec uvicorn src.api.rest.app:app --host 0.0.0.0 --port ${PORT:-8000} --reload
else
    exec uvicorn src.api.rest.app:app --host 0.0.0.0 --port ${PORT:-8000}
fi
