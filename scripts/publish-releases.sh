#!/bin/bash
# Make each tag's GitHub release carry its notes from docs/releases (docs/RELEASING.md):
# create the releases that are missing, and update those whose notes changed
# Run by .github/workflows/docker-publish.yml on a tag's build and on develop

set -euo pipefail

REPO="${GITHUB_REPOSITORY:-deduparr-dev/deduparr}"
NEWEST=$(git tag --list 'v*.*.*' --sort=-v:refname | head -n 1)

for notes in docs/releases/v*.md; do
    tag=$(basename "$notes" .md)
    # Notes written ahead of a release wait for its tag
    git rev-parse -q --verify "refs/tags/$tag" >/dev/null || continue

    if body=$(gh release view "$tag" --repo "$REPO" --json body --jq .body 2>/dev/null); then
        [ "$body" = "$(cat "$notes")" ] ||
            gh release edit "$tag" --repo "$REPO" --title "Deduparr $tag" --notes-file "$notes"
    elif [ "$tag" != "$NEWEST" ]; then
        # An older version added later must not take over as the latest release
        gh release create "$tag" --repo "$REPO" --verify-tag --title "Deduparr $tag" \
            --notes-file "$notes" --latest=false
    elif [ "${GITHUB_REF_TYPE:-}" = tag ]; then
        # The newest version's release waits for its image, which the tag's build publishes
        gh release create "$tag" --repo "$REPO" --verify-tag --title "Deduparr $tag" \
            --notes-file "$notes" --latest
    fi
done
