# GitHub Container Registry (ghcr.io) Setup

This document explains how Deduparr Docker images are built and published to GitHub Container Registry.

## 📦 Published Images

Images are automatically built and published to:
- **Registry**: `ghcr.io/deduparr-dev/deduparr`
- **Platforms**: `linux/amd64`, `linux/arm64`

## 🏷️ Image Tags

| Tag | Description | Use Case |
|-----|-------------|----------|
| `latest` | Latest stable release | Production |
| `0.1.2`, `0.1` | Specific versions | Production (pinned) |
| `dev` | Nightly from `develop` | Testing |
| `sha-*` | Specific `develop` commit | Debug |

## 🔄 Build Triggers

- **Version tag `v*.*.*`**: `latest` + semver tags (`0.1.2`, `0.1`)
- **Nightly (midnight UTC)**: `dev` + SHA from `develop`
- **Manual dispatch**: `dev` + SHA from `develop` only
- **Push to branches**: Build only (no publish)

## 🚀 Usage

### Pull Latest Stable Version

```bash
docker pull ghcr.io/deduparr-dev/deduparr:latest
```

### Pull Development Version

```bash
docker pull ghcr.io/deduparr-dev/deduparr:dev
```

### Pull Specific Version

```bash
docker pull ghcr.io/deduparr-dev/deduparr:0.1.2
```

### Use in Docker Compose

**Production (stable):**
```yaml
services:
  deduparr:
    image: ghcr.io/deduparr-dev/deduparr:latest
    # ... rest of config
```

**Development (testing new features):**
```yaml
services:
  deduparr:
    image: ghcr.io/deduparr-dev/deduparr:dev  # Development builds
    # ... rest of config
```

## 🔑 Authentication (for contributors)

GitHub Container Registry images are public by default, so no authentication is needed to pull images.

For pushing images (maintainers only), the workflow uses the automatic `GITHUB_TOKEN`.

## 🛠️ Local Development

To test the Docker build locally before pushing:

```bash
# Build for current platform
docker build -t deduparr:local .

# Build for multiple platforms (requires buildx)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t deduparr:local \
  .

# Test the image
docker run -d -p 8655:8655 deduparr:local
```

## 📋 Build Arguments

The workflow passes these build arguments:

- `BUILD_DATE`: Timestamp of the build
- `VCS_REF`: Git commit SHA
- `VERSION`: Version from git tag or branch

These can be used in the Dockerfile for metadata.

## 🔍 Verifying Images

GitHub Actions generates build attestations for all published images. You can verify an image's provenance:

```bash
# Install cosign (for verification)
gh attestation verify oci://ghcr.io/deduparr-dev/deduparr:latest \
  --owner deduparr-dev
```

## 📊 Image Optimization

Multi-stage build: Frontend (Node.js) → Backend deps → Final runtime (Python slim)

`.dockerignore` excludes tests, docs, dev configs, git history.

## 🔄 Cache Strategy

The workflow uses GitHub Actions cache (`type=gha`) to speed up builds:

- **Frontend dependencies**: Cached npm packages
- **Python dependencies**: Cached pip packages
- **Docker layers**: Cached build layers

Subsequent builds are significantly faster thanks to layer caching.

## 🏗️ Manual Workflow Dispatch

Maintainers can manually trigger a build:

1. Go to [Actions tab](https://github.com/deduparr-dev/deduparr/actions)
2. Select "Build and Publish Docker Images"
3. Click "Run workflow"
4. Choose branch:
   - **develop**: Creates `dev` + SHA tags (for testing pre-release features)
   - **main**: Build only for testing (no publish, no SHA tags)
5. Click "Run workflow"

This is useful for testing builds or creating dev snapshots without waiting for nightly builds.

## 📝 Release Process

```bash
bash scripts/release.sh 0.1.3
```

Creates tags: `latest`, `0.1.3`, `0.1` (no `0`, no SHA)

##  Resources

- [GitHub Container Registry Docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Docker Build Push Action](https://github.com/docker/build-push-action)
- [Docker Metadata Action](https://github.com/docker/metadata-action)
- [Build Attestation](https://github.blog/2024-05-02-introducing-artifact-attestations-now-in-public-beta/)
