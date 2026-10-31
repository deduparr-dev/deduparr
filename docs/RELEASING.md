# Releasing

How a version is cut, and how its release notes are written.

Each version's notes are a file in [releases/](releases/), and a workflow publishes them: the tag's
build creates the GitHub release once the image is published, and a push to `develop` publishes
changed notes and the releases of older tags. Nobody creates or edits a release by hand; a
correction is a pull request to the file.

## Cutting a release

`main` only ever receives `develop`, when a version is cut:

1. Write `docs/releases/vX.Y.Z.md` as described below, and merge it into `develop` with a pull
   request.
2. On `main`, run `git merge --no-ff origin/develop`, with `Closes #n` in the message for each
   issue the release closes.
3. Push `main` and wait for its CI/CD run to pass.
4. Run `bash scripts/release.sh X.Y.Z`. It refuses a version without notes, sets the version in
   `manifest.json`, `frontend/package.json` and its lockfile, commits
   `chore: bump version to X.Y.Z`, and pushes the commit and the tag `vX.Y.Z`.
5. The tag's build publishes the image as `latest`, `X.Y.Z` and `X.Y`, then the release
   `Deduparr vX.Y.Z` with the notes.
6. Bring `develop` up to `main`: fast-forward it, or merge `main` into it if Dependabot merged
   something in the meantime, as its pull requests merge themselves.

## Release notes

Read [v0.6.0's notes](releases/v0.6.0.md) before writing new ones and copy them: one short line
per item, glanceable in seconds. Write them in this order:

1. **Generate the list of changes**, which also ends the notes with the Full Changelog link:

   ```bash
   bash scripts/release-changes.sh <previous tag> vX.Y.Z origin/develop
   ```

2. **Read every pull request and commit in it**, then write the Summary and the bullets from them.
3. **Put the Summary and the sections above the list**, as in the template.

```markdown
## Summary

A short paragraph in normal prose: the release's theme and its largest changes.

A second paragraph only if updating changes something or needs an action.

## Breaking
• **Area**: what the user must do

## Bug fixes
• **Area**: what the user notices, in about ten words

## Enhancements
• **Area**: what the user gets, in about ten words

## Removed
• **Area**: what is gone, and what replaces it

<details>
<summary>Changes included in this release</summary>

* Pull request title by @author in #n
* Commit subject, for a change that came without a pull request

</details>

**Full Changelog**: https://github.com/deduparr-dev/deduparr/compare/<previous tag>...vX.Y.Z
```

- **Summary**: one or two short paragraphs on the highlights and the largest changes. Mention the
  update itself only when it changes a setting or needs an action; never state the obvious ("your
  settings carry over"). Big picture only; the bullets carry the details.
- **Write for someone with no technical knowledge.** Everyday words, what it means for their
  library: "another show's episode is no longer deleted", not "files were matched by name alone".
  No internal terms (pipeline, stage, adapter, migration), no file or function names.
- Sections are Summary, Bug fixes, Enhancements; Breaking and Removed only when they apply.
- Bullets are `•`. Backticks for symbols. Omit empty sections.
- **Write the summary as normal paragraphs**: related sentences run on in one paragraph, and a
  blank line separates paragraphs. Never break a line inside a paragraph or a bullet: GitHub shows
  every line break in a release.
- **One short line per item: what the user notices.** No cause, no mechanism, no semicolons, no
  second clause. Label by area (Deletion, Setup wizard), not by pull request.
- **About fifteen bullets at most.** Fold the small ones into one "Smaller fixes" line.
- No callout blocks, no known-issues essay, no explanation of the release process.
- The reasoning and the measurements belong in the pull requests and commit messages, which stay
  fully detailed. The release note is for someone glancing at it.
- **Source of truth is the diff since the previous tag**, not a pull request's description:
  `git log --oneline --no-merges <previous tag>..origin/develop` and
  `git diff <previous tag>..origin/develop`.
- **Describe the net change against the previous release.** A bug introduced and fixed between two
  releases is not a fix, and claiming it is puts a false statement in a public note. Check the old
  tag, not the pull request that introduced the intermediate state.
- Mark a superseded release with one line pointing at its replacement.
