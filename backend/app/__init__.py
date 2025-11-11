"""Deduparr application package."""

import json
from pathlib import Path

# Load version from manifest.json (single source of truth)
# __file__ is /app/app/__init__.py, so go up 2 levels to /app/
_manifest_path = Path(__file__).parent.parent / "manifest.json"

if _manifest_path.exists():
    with open(_manifest_path) as _f:
        _manifest = json.load(_f)
else:
    # Fallback for tests - use default values
    _manifest = {
        "version": "0.1.0-dev",
        "name": "Deduparr",
        "description": "Duplicate media management for the *arr ecosystem",
    }

DEDUPARR_VERSION = _manifest["version"]
DEDUPARR_NAME = _manifest["name"]
DEDUPARR_DESCRIPTION = _manifest["description"]
