# ---------- Stage 1: build dependencies + bake data artifacts ----------
FROM python:3.11-slim AS builder

WORKDIR /app

# Install the package (and all runtime dependencies) into site-packages
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Build the data artifacts inside the image:
#  - SQLite employee DB from the committed IBM HR dataset
#  - Chroma vector index from the committed handbook pages
#    (first run downloads the ONNX embedding model into ~/.cache/chroma)
COPY data ./data
COPY scripts ./scripts
RUN python data/seed_db.py --db /app/storage/hr.db \
 && python scripts/ingest.py

# ---------- Stage 2: minimal runtime image ----------
FROM python:3.11-slim

# onnxruntime (query-time embeddings) needs OpenMP on slim images
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1001 app

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder --chown=app:app /app/storage ./storage
# the embedding model cache must ship with the image (offline at runtime)
COPY --from=builder --chown=app:app /root/.cache/chroma /home/app/.cache/chroma

COPY --chown=app:app src ./src
COPY --chown=app:app static ./static

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app \
    PORT=8080 \
    ENV=prod

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["python", "-m", "hr_assistant"]
