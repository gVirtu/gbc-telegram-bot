FROM python:3.11-slim-bookworm

# Create non-root user first
RUN groupadd -r appgroup && useradd -r -g appgroup -u 1000 appuser

# Install runtime dependencies including ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && rm -rf /var/cache/apt/*

WORKDIR /app

# Copy application code first (for layer caching of deps)
COPY --chown=appuser:appgroup pyproject.toml ./

# Install Python dependencies from pyproject.toml
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy source code and assets
COPY --chown=appuser:appgroup src/ ./src/
COPY --chown=appuser:appgroup assets/ ./assets/
COPY --chown=appuser:appgroup i18n/ ./i18n/

# Create directories for volumes
RUN mkdir -p /app/data /app/roms && \
    chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" 2>/dev/null || exit 1

# Environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8000
ENV WEB_CONCURRENCY=1

# Reduce glibc malloc fragmentation. MALLOC_ARENA_MAX caps the number of
# per-thread arenas (default: 8×nCPU); without this, freed numpy arrays leave
# large holes in many arenas that glibc never returns to the OS.
# MALLOC_MMAP_THRESHOLD_ / MALLOC_TRIM_THRESHOLD_ tell glibc to use mmap for
# allocations above 128 KB (mmap'd memory IS returned to the OS on free) and
# to trim the heap more aggressively between batches.
ENV MALLOC_ARENA_MAX=2
ENV MALLOC_MMAP_THRESHOLD_=131072
ENV MALLOC_TRIM_THRESHOLD_=131072

ENV DATA_DIR=/app/data
ENV TBC_OVERLAY_PATH=/app/assets/to_be_continued.png

# Run uvicorn with multiple workers
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
