#!/bin/bash
# Print the end of a version's release notes (docs/RELEASING.md): every change since the
# previous version, as its pull request when it came from one, and the Full Changelog link
# Usage: bash scripts/release-changes.sh <previous tag> <new tag> [<last commit>]
# Before cutting 0.6.1: bash scripts/release-changes.sh v0.6.0 v0.6.1 origin/develop

set -euo pipefail

PREVIOUS="$1"
NEW="$2"
LAST="${3:-$NEW}"
REPO="deduparr-dev/deduparr"

# Each merged pull request as GitHub's own release notes show it: its title and who opened it
declare -A PULLS
while read -r number pull; do
    PULLS[$number]=$pull
done < <(gh pr list --repo "$REPO" --state merged --limit 5000 --json number,title,author \
    --jq '.[] | "\(.number) \(.title) by @\(if .author.is_bot then (.author.login | ltrimstr("app/")) + "[bot]" else .author.login end)"')

echo "<details>"
echo "<summary>Changes included in this release</summary>"
echo
# A squash-merged pull request's commit ends with its number
git log --reverse --no-merges --format=%s "$PREVIOUS..$LAST" | { grep -v '^chore: bump version to ' || true; } |
    while read -r subject; do
        number=$(grep -oE '\(#[0-9]+\)$' <<<"$subject" | tr -d '(#)' || true)
        if [ -n "$number" ] && [ -n "${PULLS[$number]:-}" ]; then
            echo "* ${PULLS[$number]} in #$number"
        else
            echo "* $subject"
        fi
    done
echo
echo "</details>"
echo
echo "**Full Changelog**: https://github.com/$REPO/compare/$PREVIOUS...$NEW"
