FROM python:3.11-slim-bookworm

ARG TARGETARCH

# Create non-root user first
RUN groupadd -r appgroup && useradd -r -g appgroup -u 1000 appuser

# Install runtime dependencies and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libjemalloc2 \
    build-essential \
    clang \
    lld \
    cmake \
    git \
    nasm \
    yasm \
    pkg-config \
    libx264-dev \
    && \
    export CFLAGS="-O3" && \
    export CXXFLAGS="-O3" && \
    export LDFLAGS="-Wl,--no-keep-memory" && \
    export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig && \
    if [ "$TARGETARCH" = "arm64" ]; then \
    export SVT_CMAKE_EXTRA="-DENABLE_NEON=ON -DENABLE_ARM_CRC32=ON -DENABLE_NEON_DOTPROD=ON -DENABLE_NEON_I8MM=OFF -DENABLE_SVE=OFF -DENABLE_SVE2=OFF"; \
    export SVT_MARCH="-march=armv8.2-a+crc+dotprod"; \
    else \
    export SVT_CMAKE_EXTRA=""; \
    export SVT_MARCH=""; \
    fi && \
    # Cap build jobs to prevent out-of-memory errors
    BUILD_JOBS=$(nproc) && \
    if [ "$BUILD_JOBS" -gt 4 ]; then BUILD_JOBS=4; fi && \
    # Build SVT-AV1 v4.1.0 from source
    git clone --depth 1 -b v4.1.0 https://gitlab.com/AOMediaCodec/SVT-AV1.git /tmp/svtav1 && \
    mkdir /tmp/svtav1_build && cd /tmp/svtav1_build && \
    cmake /tmp/svtav1 -G"Unix Makefiles" -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_AR=/usr/bin/ar -DCMAKE_RANLIB=/usr/bin/ranlib -DCMAKE_C_COMPILER_AR=/usr/bin/ar -DCMAKE_C_COMPILER_RANLIB=/usr/bin/ranlib "-DCMAKE_C_FLAGS=$SVT_MARCH" "-DCMAKE_C_FLAGS_RELEASE=-O3 -DNDEBUG -flto=thin" "-DCMAKE_EXE_LINKER_FLAGS=-fuse-ld=lld" "-DCMAKE_EXE_LINKER_FLAGS_RELEASE=-flto=thin" "-DCMAKE_SHARED_LINKER_FLAGS=-fuse-ld=lld" "-DCMAKE_SHARED_LINKER_FLAGS_RELEASE=-flto=thin" -DCMAKE_INSTALL_PREFIX=/usr/local -DBUILD_SHARED_LIBS=OFF -DBUILD_APPS=OFF -DBUILD_DEC=OFF $SVT_CMAKE_EXTRA && \
    mkdir -p /tmp/svtav1/Bin/Release && \
    make -j$BUILD_JOBS && \
    make install && \
    # Build FFmpeg from source
    git clone --depth 1 -b release/8.1 https://github.com/FFmpeg/FFmpeg.git /tmp/FFmpeg && \
    cd /tmp/FFmpeg && \
    ./configure --prefix=/usr/local --cc=clang --enable-gpl --enable-libsvtav1 --enable-libx264 --pkg-config-flags="--static" --extra-cflags="$CFLAGS" --extra-cxxflags="$CXXFLAGS" --extra-ldflags="$LDFLAGS -fuse-ld=lld" && \
    make -j$BUILD_JOBS && \
    make install && \
    # Clean up build tools and temporary files to keep image size small
    rm -rf /tmp/svtav1 /tmp/svtav1_build /tmp/FFmpeg && \
    apt-get remove -y clang lld cmake nasm yasm pkg-config && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && rm -rf /var/cache/apt/*

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

ENV DATA_DIR=/app/data
ENV TBC_OVERLAY_PATH=/app/assets/to_be_continued.png

# Run uvicorn with multiple workers
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
