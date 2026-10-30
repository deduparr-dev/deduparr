# Deduparr Documentation

Welcome to the Deduparr documentation! This directory contains technical guides and API references.

## 📚 Available Documentation

### User Guides

- **[API Usage Examples](API_USAGE_EXAMPLES.md)** - Complete guide to using the duplicate detection and deletion API
  - Scanning for duplicates
  - Previewing deletion decisions
  - Executing deletions (with dry-run support)
  - Understanding the scoring system
  - Error handling and best practices

- **[Docker Testing Guide](DOCKER_TESTING.md)** - Docker development and deployment
  - Quick start with Docker
  - Development setup options
  - Docker commands reference
  - Troubleshooting common issues

- **[Deployment Guide](../DEPLOYMENT.md)** - Production deployment with Docker Compose

- **[Deep Scan](DEEP_SCAN.md)** - The optional pass over the library folders on disk

### Project Information

- **[Contributing Guidelines](../CONTRIBUTING.md)** - How to contribute to Deduparr
  - Development setup
  - Code standards (React 19 and Python)
  - Commit conventions
  - Pull request process

- **[Security Policy](SECURITY.md)** - Security practices and reporting
  - NPM supply chain protection
  - Type safety requirements
  - Vulnerability reporting
  - Code security standards

- **[Releasing](RELEASING.md)** - How a version is cut, and how its release notes are written

- **[Dependabot Auto-Merge](DEPENDABOT_AUTO_MERGE.md)** - How dependency updates are proposed and merged

- **[GHCR Setup](GHCR_SETUP.md)** - How the Docker images are built and published

## 🎯 Quick Links

### For Users
- [Main README](../README.md) - Project overview and quick start
- [API Examples](API_USAGE_EXAMPLES.md) - Learn how to use the API
- API reference - `/api/docs` on a running instance (OpenAPI at `/api/openapi.json`)

### For Developers
- [Contributing](../CONTRIBUTING.md) - Development guidelines
- [Docker Testing](DOCKER_TESTING.md) - Local development with Docker
- [Releasing](RELEASING.md) - Cutting a version, and its release notes in [releases/](releases/)
- [Implementation Plan](../todo/IMPLEMENTATION_PLAN.md) - Feature roadmap and technical design

### For DevOps
- [Docker Compose](../docker-compose.yml) - Production deployment
- [Podman quadlets](../quadlet/README.md) - Development environment

## 🔗 External Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/) - Backend framework
- [React 19 Documentation](https://react.dev/) - Frontend framework
- [PlexAPI Documentation](https://python-plexapi.readthedocs.io/) - Plex integration
- [Radarr API](https://radarr.video/docs/api/) - Radarr integration
- [Sonarr API](https://sonarr.tv/docs/api/) - Sonarr integration

## 📝 Documentation Status

| Document | Status | Last Updated |
|----------|--------|--------------|
| API_USAGE_EXAMPLES.md | ✅ Complete | Current |
| DOCKER_TESTING.md | ✅ Complete | Current |
| README.md (main) | ✅ Complete | Current |
| CONTRIBUTING.md | ✅ Complete | Current |
| SECURITY.md | ✅ Complete | Current |
| DEPLOYMENT.md | ✅ Complete | Current |
| DEEP_SCAN.md | ✅ Complete | Current |
| RELEASING.md | ✅ Complete | Current |
| DEPENDABOT_AUTO_MERGE.md | ✅ Complete | Current |
| GHCR_SETUP.md | ✅ Complete | Current |

## 🚧 Planned Documentation

The following documentation is planned for future releases:

- **Installation Guide** - Detailed installation instructions for various platforms
- **Configuration Guide** - Complete configuration reference
- **Scoring System** - Deep dive into the quality scoring algorithm
- **Troubleshooting** - Common issues and solutions

## 💡 Need Help?

- Check the [API Usage Examples](API_USAGE_EXAMPLES.md) for practical examples
- Review [Contributing Guidelines](../CONTRIBUTING.md) for development help
- Open an issue on [GitHub](https://github.com/deduparr-dev/deduparr/issues)
