# GitHub Container Registry (ghcr.io) Setup

This document explains how Deduparr Docker images are built and published to GitHub Container Registry.

## 📦 Published Images

Images are automatically built and published to:
- **Registry**: `ghcr.io/deduparr-dev/deduparr`
- **Platforms**: `linux/amd64`, `linux/arm64`

## 🏷️ Image Tags

| Tag | Description | When Updated | Use Case |
|-----|-------------|--------------|----------|
| `latest` | Latest stable release from `main` branch | On push to `main` | **Production** - Most users |
| `dev` | Development version from `develop` branch | On push to `develop` | **Testing** - Early adopters |
| `v*.*.*` | Specific version tags (e.g., `v1.0.0`) | On Git tags matching `v*.*.*` | **Production** - Pin to version |
| `main-sha-*` | Specific commit from `main` branch | On every commit to `main` | **Debug** - Specific production build |
| `develop-sha-*` | Specific commit from `develop` branch | On every commit to `develop` | **Debug** - Specific dev build |

## 🔄 Automated Builds

The GitHub Actions workflow (`.github/workflows/docker-publish.yml`) automatically:

1. **Builds** multi-platform images (amd64 + arm64)
2. **Tags** images based on branch/tag
3. **Pushes** to GitHub Container Registry
4. **Caches** build layers for faster subsequent builds
5. **Generates** build attestation for security

### Triggers

- **Push to `main`**: Creates `latest` tag
- **Push to `develop`**: Creates `develop` tag
- **Push tag `v*.*.*`**: Creates version tags (e.g., `v1.0.0`, `1.0`, `1`)
- **Pull Requests**: Builds but doesn't push (validates only)
- **Manual**: Can be triggered via GitHub Actions UI

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
docker pull ghcr.io/deduparr-dev/deduparr:v1.0.0
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

## 📊 Image Size Optimization

The multi-stage Dockerfile optimizes image size by:

1. **Stage 1**: Build frontend (Node.js)
2. **Stage 2**: Install Python dependencies
3. **Stage 3**: Final runtime image (Python slim)
   - Only includes runtime dependencies
   - Frontend is pre-built static files
   - No build tools in final image

The `.dockerignore` file excludes:
- Tests and test data
- Documentation
- Development configs
- Git history
- Node modules and build artifacts

This keeps the Docker build context small and fast.

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
4. Choose branch and click "Run workflow"

This is useful for rebuilding images without making code changes (e.g., to pull in base image security updates).

## 📝 Release Process

To create a new release:

1. Update version in code if needed
2. Commit changes to `develop`
3. Merge `develop` → `main` (creates `latest` tag)
4. Create Git tag: `git tag v1.0.0 && git push --tags`
5. Workflow automatically builds and publishes versioned images

## 🐛 Troubleshooting

### Build Fails

Check the [Actions tab](https://github.com/deduparr-dev/deduparr/actions) for build logs.

Common issues:
- **Multi-platform build timeout**: ARM64 builds can be slow. Consider splitting platforms if needed.
- **Cache corruption**: Clear cache by re-running workflow with cache disabled.
- **Registry authentication**: Ensure repository has proper permissions for `GITHUB_TOKEN`.

### Image Not Found

- **Check tag exists**: Visit [Packages](https://github.com/deduparr-dev/deduparr/pkgs/container/deduparr)
- **Wait for build**: Check if workflow is still running
- **Verify branch/tag**: Ensure you pushed to correct branch

### Permission Denied

Images are public by default. If you see permission errors:
- **Check package visibility**: Go to package settings
- **Verify public access**: Should be enabled for `ghcr.io/deduparr-dev/deduparr`

## 🔗 Resources

- [GitHub Container Registry Docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Docker Build Push Action](https://github.com/docker/build-push-action)
- [Docker Metadata Action](https://github.com/docker/metadata-action)
- [Build Attestation](https://github.blog/2024-05-02-introducing-artifact-attestations-now-in-public-beta/)
