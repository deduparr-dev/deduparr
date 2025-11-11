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

# Update version in manifest.json
echo "Updating version in manifest.json to $VERSION"
sed -i "s/\"version\": \".*\"/\"version\": \"$VERSION\"/" manifest.json

# Update version in frontend/package.json
echo "Updating version in frontend/package.json to $VERSION"
sed -i "s/\"version\": \".*\"/\"version\": \"$VERSION\"/" frontend/package.json

# Update package-lock.json
echo "Updating frontend/package-lock.json"
cd frontend
npm install --package-lock-only
cd ..

# Commit version changes
echo "Committing version bump to $VERSION"
git add manifest.json frontend/package.json frontend/package-lock.json
git commit -m "chore: bump version to $VERSION"

# Create the tag
echo "Creating tag: $TAG"
git tag -a "$TAG" -m "Release $TAG"

# Push changes and tag
echo "Pushing to origin..."
git push origin main
git push origin "$TAG"

echo "Release $TAG created and pushed successfully"
echo "Monitor build: https://github.com/deduparr-dev/deduparr/actions"

