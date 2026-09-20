#!/bin/sh
set -eu

# Bring the durable schema up to date before checking the external AI service.
alembic -c alembic.ini upgrade head

# Fail before accepting uploads if this container cannot reach the configured AI model.
python scripts/check_openai_runtime.py
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
