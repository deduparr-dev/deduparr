#!/bin/bash
# Generate the next Alembic migration from what the models changed
# Usage: bash scripts/new-migration.sh "Describe the change"
#
# Upgrades a throwaway SQLite database to the newest migration, compares it
# with the models and writes the difference to
# backend/alembic/versions/<next number>_<description>.py

set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "Usage: bash scripts/new-migration.sh \"Describe the change\""
    exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR/backend"

SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
export DATABASE_TYPE=sqlite
export DATABASE_URL="sqlite:///$SCRATCH/head.db"
export CONFIG_DIR="$SCRATCH"

python -m alembic upgrade head > /dev/null
if python -m alembic check > /dev/null 2>&1; then
    echo "The models match the newest migration: there is nothing to generate."
    exit 0
fi

LAST=$(ls alembic/versions | grep -oE '^[0-9]{4}' | sort | tail -1)
NEXT=$(printf '%04d' $((10#${LAST:-0} + 1)))
python -m alembic revision --autogenerate --rev-id "$NEXT" -m "$1"
