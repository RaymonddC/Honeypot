FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8000

# Entrypoint runs `alembic upgrade head` (when ITTU_PERSISTENCE=postgres +
# ITTU_MIGRATION_DATABASE_URL is set) before starting uvicorn — so schema
# changes deploy automatically. See backend/scripts/start.sh.
CMD ["sh", "scripts/start.sh"]
