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
passed, it approves the pull request, since `develop` requires an approval, and
squash-merges it, but only the commit CI passed on: if Dependabot pushed a newer
one in the meantime, that one waits for its own run. Approving needs the
repository setting "Allow GitHub Actions to create and approve pull requests".

The workflow runs from `main`'s copy, as every `workflow_run` workflow does, so
a change to it takes effect when a version is cut.

CI is what stands between an update and `develop`: backend lint and tests,
frontend lint and build, the end-to-end tests, building the Docker image and
starting it, and the security audit's `pip-audit` (its `npm audit` only
reports). Every kind of update is merged when all of that passes, major
versions included.

A merge made with the workflow's token starts no workflow on `develop`, so the
nightly build is what publishes these updates to the `dev` image.

## When Something Fails

A pull request whose CI fails stays open: fix what broke, or close it.
Dependabot rebases its pull requests itself when they conflict
(`rebase-strategy: auto`).
