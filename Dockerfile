FROM python:3.11-slim-bookworm

ARG TARGETARCH

# Create non-root user first
RUN groupadd -r appgroup && useradd -r -g appgroup -u 1000 appuser

# Add Debian sid repository, pinned low so bookworm packages are preferred by
# default; FFmpeg + SVT-AV1 4.1.0 are pulled from sid explicitly.
RUN echo 'deb http://deb.debian.org/debian sid main' > /etc/apt/sources.list.d/sid.list && \
    printf 'Package: *\nPin: release a=stable\nPin-Priority: 900\n\nPackage: *\nPin: release a=unstable\nPin-Priority: 100\n' \
    > /etc/apt/preferences.d/prefer-stable

# Install runtime deps; pull FFmpeg (with SVT-AV1 4.1.0) and dev headers from
# sid; compile PyAV from source so it links against the system FFmpeg; then
# strip the dev headers and pkg-config to keep the image lean.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libjemalloc2 \
    build-essential \
    git \
    pkg-config && \
    apt-get -o Dpkg::Options::="--force-overwrite" install -y --no-install-recommends -t sid \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    libavdevice-dev \
    libavfilter-dev && \
    pip install --no-cache-dir --no-binary av "av>=14.0.0" && \
    apt-get remove -y --purge \
    pkg-config \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    libavdevice-dev \
    libavfilter-dev && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean && \
    rm -rf /var/cache/apt/*

# Use jemalloc instead of glibc malloc to reduce memory fragmentation.
# glibc ptmalloc retains freed numpy array pages in per-thread arenas and
# never returns them to the OS; jemalloc's size-class binning and aggressive
# MADV_FREE/DONTNEED calls recover that memory after each batch.
# Symlink to a fixed path so LD_PRELOAD works on both amd64 and arm64.
RUN find /usr/lib -name "libjemalloc.so.2" -exec ln -sf {} /usr/local/lib/libjemalloc.so.2 \;
ENV LD_PRELOAD=/usr/local/lib/libjemalloc.so.2

WORKDIR /app

# Copy application code first (for layer caching of deps)
COPY --chown=appuser:appgroup pyproject.toml ./

# Install Python dependencies from pyproject.toml.
# --no-binary av ensures av is never silently swapped to the PyPI wheel
# (which bundles an older SVT-AV1) on a cache-invalidated rebuild.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --no-binary av .

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

ENV DATA_DIR=/app/data
ENV TBC_OVERLAY_PATH=/app/assets/to_be_continued.png

# Run uvicorn with multiple workers
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
