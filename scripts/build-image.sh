#!/bin/bash
set -euo pipefail

# Build and push multi-arch Docker images
# Usage: ./scripts/build-image.sh [registry] [push]
#   registry: Docker registry (default: docker.io/gvirtu)
#   push: Set to "push" to actually push (default: dry-run)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Configuration
REGISTRY="${1:-docker.io/gvirtu}"
SHOULD_PUSH="${2:-}"
IMAGE_NAME="pyboy-telegram-bot"
DEFAULT_TAG="${3:-latest}"

# Extract version from pyproject.toml
VERSION=$(grep '^version = ' "${PROJECT_ROOT}/pyproject.toml" | sed 's/version = "\([^"]*\)"/\1/')
if [ -z "$VERSION" ]; then
    echo "ERROR: Could not extract version from pyproject.toml"
    exit 1
fi

# Parse version components for rolling tags
MAJOR=$(echo "$VERSION" | cut -d. -f1)
MINOR=$(echo "$VERSION" | cut -d. -f2)

# Full image name
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}"

echo "=========================================="
echo "Building Docker Images"
echo "=========================================="
echo "Version: $VERSION"
echo "Image: $FULL_IMAGE"
echo "Tag: $DEFAULT_TAG"
echo "Platforms: linux/amd64, linux/arm64"
echo "=========================================="
echo ""

# Check if buildx builder exists, create if not
if ! docker buildx inspect multiarch-builder &>/dev/null; then
    echo "Creating multiarch builder..."
    docker buildx create --name multiarch-builder --driver docker-container --use
else
    echo "Using existing multiarch builder..."
    docker buildx use multiarch-builder
fi

# Determine build mode
if [ "$SHOULD_PUSH" = "push" ]; then
    echo "PUSH MODE: Will push multi-arch images to registry"
    
    # Build arguments for multi-arch push
    BUILD_ARGS=(
        --platform linux/amd64,linux/arm64
        --tag "${FULL_IMAGE}:${DEFAULT_TAG}"
        --tag "${FULL_IMAGE}:${VERSION}"
        --tag "${FULL_IMAGE}:${MAJOR}.${MINOR}"
        --tag "${FULL_IMAGE}:${MAJOR}"
        --push
    )
    
    # Build the multi-arch images
    echo ""
    echo "Building multi-arch images..."
    docker buildx build "${BUILD_ARGS[@]}" "${PROJECT_ROOT}"
    
    # Also create explicit platform-specific tags
    echo ""
    echo "Creating explicit platform-specific tags..."
    
    for platform in linux/amd64 linux/arm64; do
        platform_tag=$(echo "$platform" | tr '/' '-')
        echo "  - Building ${platform} as ${VERSION}-${platform_tag}"
        
        docker buildx build \
            --platform "$platform" \
            --tag "${FULL_IMAGE}:${VERSION}-${platform_tag}" \
            --push \
            "${PROJECT_ROOT}"
    done
else
    echo "DRY-RUN MODE: Building single-platform image locally"
    echo "  (Use 'push' argument to build and push multi-arch images)"
    
    # Build arguments for local single-platform build
    BUILD_ARGS=(
        --tag "${FULL_IMAGE}:${DEFAULT_TAG}"
        --tag "${FULL_IMAGE}:${VERSION}"
        --load
    )
    
    # Build locally for native platform only
    echo ""
    echo "Building for native platform..."
    docker buildx build "${BUILD_ARGS[@]}" "${PROJECT_ROOT}"
fi

echo ""
echo "=========================================="
echo "Build Complete!"
echo "=========================================="
echo ""
echo "Tags created:"
echo "  - ${FULL_IMAGE}:${DEFAULT_TAG}"
echo "  - ${FULL_IMAGE}:${VERSION}"
echo "  - ${FULL_IMAGE}:${MAJOR}.${MINOR}"
echo "  - ${FULL_IMAGE}:${MAJOR}"

if [ "$SHOULD_PUSH" = "push" ]; then
    echo "  - ${FULL_IMAGE}:${VERSION}-linux-amd64"
    echo "  - ${FULL_IMAGE}:${VERSION}-linux-arm64"
fi

echo ""
echo "To verify the multi-arch manifest:"
echo "  docker manifest inspect ${FULL_IMAGE}:${VERSION}"
echo ""
