# Optimiza Conversacional — imagen única (API + frontend estático)
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OPTIMIZA_DATA_DIR=/app/data \
    OPTIMIZA_FRONTEND_DIR=/app/frontend/static

WORKDIR /app

# Dependencias del sistema mínimas (psycopg2-binary no requiere compilación)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt requirements-redshift.txt ./
ARG INSTALL_REDSHIFT=true
RUN pip install -r requirements.txt \
    && if [ "$INSTALL_REDSHIFT" = "true" ]; then pip install psycopg2-binary; fi

COPY backend ./backend
COPY frontend ./frontend
COPY tests ./tests
COPY pytest.ini ./pytest.ini

# Genera los Parquet de demo en la imagen para que el arranque sea inmediato
RUN python -m backend.app.seed.generate_seed

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=5 \
  CMD curl -fs http://localhost:8000/api/salud || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
