#!/bin/bash
# Print the Python and Node versions the Dockerfile builds on
# Usage in a workflow: bash scripts/versions.sh >> "$GITHUB_OUTPUT"
#
# Dependabot keeps the Dockerfile's base images current, and CI reads the
# versions from here, so CI always tests what the image ships.

set -euo pipefail

DOCKERFILE="$(cd "$(dirname "$0")/.." && pwd)/Dockerfile"

python=$(sed -n 's/^FROM python:\([0-9.]*\)-slim.*/\1/p' "$DOCKERFILE" | head -1)
node=$(sed -n 's/^FROM node:\([0-9.]*\)-alpine.*/\1/p' "$DOCKERFILE" | head -1)

if [ -z "$python" ] || [ -z "$node" ]; then
    echo "Could not read the Python and Node versions from $DOCKERFILE" >&2
    exit 1
fi

echo "python=$python"
echo "node=$node"
