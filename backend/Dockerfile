# SyncForge backend image: the API, the Celery worker, the outbox relay and the
# migration job all run from this image with different commands (docker-compose.yml).

# ---- build: install dependencies into a virtual environment --------------------------
FROM python:3.13-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install -r /tmp/requirements.txt

# ---- runtime -------------------------------------------------------------------------
FROM python:3.13-slim
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --home-dir /app syncforge
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
USER syncforge
EXPOSE 8000
# Default role: the API. Uvicorn trusts X-Forwarded-For only when FORWARDED_ALLOW_IPS
# says so; docker-compose.yml sets it because only the nginx container can reach the API.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
