FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8000

# Bind to $PORT when the platform provides one (Render/Fly/Cloud Run); else 8000.
# Shell form so ${PORT} expands.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
