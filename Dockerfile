# ============================================================
# docfold — Docker image
# Multi-stage build: install deps → slim runtime
# ============================================================
# Usage:
#   docker build -t docfold .                              # CPU-only (lean)
#   docker build -t docfold --build-arg ENABLE_GPU=true .  # GPU (CUDA + torch)
#
#   docker run -e DOCFOLD_MODE=api  -p 8000:8000 docfold
#   docker run -e DOCFOLD_MODE=worker docfold

# ---------- Stage 1: Builder ----------
FROM python:3.12-slim AS builder

# GPU flag — controls whether torch-dependent OCR engines are installed
ARG ENABLE_GPU=false

WORKDIR /build

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# pipeline-common: shared schemas + middleware (incl. TenantMiddleware),
# consumed as a secondary build context. See parent docker-compose.yml
# ``additional_contexts: pipeline_common: ./pipeline-common``. When this
# image is built standalone (without the additional context), the COPY
# below will fail by design — docfold's API depends on pipeline-common.
COPY --from=pipeline_common . /build/pipeline-common/

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

# Install the package + pipeline-common in a single pip invocation so
# both share one dependency resolution (matches chunking's pattern).
#   CPU mode:  API + pipeline-common — lean image (~400MB)
#   GPU mode:  + nougat, surya, easyocr, lightonocr (torch-dependent OCR engines)
#              Uses PyTorch CUDA 12.4 index — wheels bundle their own CUDA runtime
RUN if [ "$ENABLE_GPU" = "true" ]; then \
        echo "==> GPU mode: installing torch-dependent OCR engines with CUDA support" && \
        pip install --no-cache-dir --prefix=/install \
            --extra-index-url https://download.pytorch.org/whl/cu121 \
            ".[api,nougat,surya,easyocr,lightonocr]" /build/pipeline-common/; \
    else \
        echo "==> CPU mode: installing API-only (no torch)" && \
        pip install --no-cache-dir --prefix=/install ".[api]" /build/pipeline-common/; \
    fi

# ---------- Stage 2: Runtime ----------
FROM python:3.12-slim AS runtime

ARG ENABLE_GPU=false

WORKDIR /app

# Install system deps for document processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    poppler-utils \
    tesseract-ocr \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY src/ src/
COPY scripts/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create non-root user and required data directories
RUN useradd -m -r docfold && \
    mkdir -p /tmp/docfold/uploads /tmp/docfold/results \
             /data/uploads /data/results && \
    chown -R docfold:docfold /tmp/docfold /data /app

USER docfold

# Environment defaults
# NVIDIA env vars enable GPU passthrough when container has GPU reservation
ENV DOCFOLD_HOST=0.0.0.0 \
    DOCFOLD_PORT=8000 \
    DOCFOLD_WORKERS=1 \
    DOCFOLD_LOG_LEVEL=info \
    DOCFOLD_REDIS_URL=redis://redis:6379 \
    DOCFOLD_MODE=api \
    ENABLE_GPU=${ENABLE_GPU} \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
