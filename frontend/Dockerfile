# Local Apple Studio — frontend API/UI only (no mflux).
# Generation runs on the macOS backend via ENGINE_URL.
# Built and run by ./launcher.sh (context: frontend/).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENGINE_MODE=remote \
    ENGINE_URL=http://host.docker.internal:8090 \
    STUDIO_ROOT=/app \
    STUDIO_OUTPUTS_DIR=/data/outputs \
    STUDIO_UPLOADS_DIR=/data/uploads

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 studio

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY web /app/web
COPY catalog /app/catalog

# uid 1000 is paired with launcher.sh --tmpfs uid=1000 for /tmp and /data.
RUN mkdir -p /data/outputs /data/uploads \
    && chown -R studio:studio /app /data

USER studio
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

CMD ["python", "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8080"]
