# Dependabot Auto-Merge

Dependabot keeps every dependency current, and a pull request it opens is
merged on its own once CI passes on it.

## What Dependabot Updates

[dependabot.yml](../.github/dependabot.yml) checks every Monday, against
`develop`:

- **pip**: `backend/requirements.txt`
- **npm**: `frontend/package.json` and its lockfile
- **GitHub Actions**: every workflow
- **Docker**: the base images of `Dockerfile`, `backend/Dockerfile.dev` and
  `frontend/Dockerfile.dev`, in one pull request per image for all three. This
  is how Python and Node move to a new version.

CI reads the Python and Node versions from the `Dockerfile`
([scripts/versions.sh](../scripts/versions.sh)), so a base image update moves
CI with it.

Dependabot waits three days before proposing a new release, as a guard against
compromised packages. Docker images are exempt: the official images re-push
their tags every few days, so the wait never ended and no Python or Node update
was ever proposed.

## How a Pull Request Gets Merged

[dependabot-auto-merge.yml](../.github/workflows/dependabot-auto-merge.yml)
runs when the CI/CD workflow finishes on a Dependabot pull request. If CI
passed, it waits for the other required checks and squash-merges the pull
request, but only the commit CI passed on: if Dependabot pushed a newer one in
the meantime, that one waits for its own run.

Only a [code owner](../.github/CODEOWNERS) can approve a pull request into
`develop`, so the merge goes through a GitHub App on `develop`'s bypass list,
for pull requests only. The App has write access to contents, pull requests and
workflows, and read access to actions and checks. Its ID and private key are the
`MERGE_APP_ID` and `MERGE_APP_KEY` secrets of the `merge` environment, which only
`main` can use, so a workflow on another branch cannot read them.

The workflow runs from `main`'s copy, as every `workflow_run` workflow does, so
a change to it takes effect when a version is cut.

CI is what stands between an update and `develop`: backend lint and tests,
frontend lint and build, the end-to-end tests, building the Docker image and
starting it, and the security audit's `pip-audit` (its `npm audit` only
reports). Every kind of update is merged when all of that passes, major
versions included.

A merge made with the App's token is a push like any other, so it runs CI on
`develop` and publishes the `dev` image.

## When Something Fails

A pull request whose CI fails stays open: fix what broke, or close it.
Dependabot rebases its pull requests itself when they conflict
(`rebase-strategy: auto`).
