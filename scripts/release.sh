#!/bin/bash
# Release script for Deduparr
# Creates and pushes a version tag to trigger Docker image build and publish
# Usage: bash scripts/release.sh 1.0.0

set -e

# Check if version argument is provided
if [ -z "$1" ]; then
    echo "Error: Version number required"
    echo "Usage: bash scripts/release.sh <version>"
    echo "Example: bash scripts/release.sh 1.0.0"
    exit 1
fi

VERSION="$1"

# Ensure version doesn't already have 'v' prefix
if [[ "$VERSION" == v* ]]; then
    VERSION="${VERSION#v}"
fi

TAG="v$VERSION"

# Check if on main branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "Error: Must be on main branch to create a release"
    echo "Current branch: $CURRENT_BRANCH"
    exit 1
fi

# Check if there are uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo "Error: Working directory has uncommitted changes"
    echo "Please commit or stash your changes before creating a release"
    exit 1
fi

# Pull latest changes
echo "Pulling latest changes from origin/main..."
git pull origin main

# Check if tag already exists
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "Error: Tag $TAG already exists"
    exit 1
fi

# Create the tag
echo "Creating tag: $TAG"
git tag -a "$TAG" -m "Release $TAG"

# Push the tag
echo "Pushing tag to origin..."
git push origin "$TAG"

echo "Release $TAG created and pushed successfully"
echo "Monitor build: https://github.com/deduparr-dev/deduparr/actions"

