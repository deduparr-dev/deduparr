# Dependabot Auto-Merge Setup

This project uses GitHub Actions to automatically approve and merge Dependabot pull requests that pass all CI checks.

## How It Works

The [dependabot-auto-merge.yml](../.github/workflows/dependabot-auto-merge.yml) workflow:

1. **Triggers** on pull requests to the `develop` branch
2. **Filters** to only run for Dependabot PRs (`github.actor == 'dependabot[bot]'`)
3. **Fetches metadata** using `dependabot/fetch-metadata@v2` to determine update type
4. **Auto-approves** patch and minor version updates
5. **Enables auto-merge** with squash merge strategy

## What Gets Auto-Merged

The workflow automatically approves and merges:
- **Patch updates** (e.g., 1.2.3 → 1.2.4) - Bug fixes
- **Minor updates** (e.g., 1.2.0 → 1.3.0) - New features (backward compatible)

**Major updates** (e.g., 1.0.0 → 2.0.0) require manual review and approval.

## Requirements

### Branch Protection Rules

For auto-merge to work, you need to configure branch protection on `develop`:

1. Go to **Settings → Branches → Branch protection rules**
2. Add rule for `develop` branch with:
   - ✅ **Require status checks to pass before merging**
     - Enable: `Backend Lint & Test`
     - Enable: `Frontend Lint & Build`
     - Enable: `Docker Build Test`
     - Enable: `NPM Security Audit`
     - Enable: `Python Security Audit`
   - ✅ **Require branches to be up to date before merging**
   - ✅ **Allow auto-merge**

### GitHub Actions Permissions

The workflow requires these permissions (already configured in the workflow file):
- `pull-requests: write` - To approve PRs
- `contents: write` - To enable auto-merge

## Testing the Workflow

To test the workflow:

1. Wait for Dependabot to create a PR
2. Check that CI passes
3. Verify the workflow runs and approves/enables auto-merge
4. Once CI completes, the PR should merge automatically

## Customization

### Change Auto-Merge Strategy

To use a different merge strategy, edit line 35 in the workflow:
```yaml
run: gh pr merge --auto --squash "$PR_URL"  # Change --squash to --merge or --rebase
```

### Auto-Merge All Updates (Including Major)

Remove the `if` conditions on steps "Auto-approve" and "Enable auto-merge":
```yaml
- name: Auto-approve Dependabot PR
  # Remove the if: condition
  run: gh pr review --approve "$PR_URL"
```

**⚠️ Warning:** Auto-merging major updates can introduce breaking changes!

### Specific Package Rules

To only auto-merge specific packages, add a condition:
```yaml
if: |
  (steps.metadata.outputs.update-type == 'version-update:semver-patch' ||
   steps.metadata.outputs.update-type == 'version-update:semver-minor') &&
  steps.metadata.outputs.dependency-names contains 'your-package-name'
```

## Dependabot Configuration

The existing [dependabot.yml](../.github/dependabot.yml) configures:
- **npm** updates for `/frontend`
- **pip** updates for `/backend`
- **Docker** base image updates
- Weekly schedule (Mondays)
- Grouped updates for related packages

## Troubleshooting

### Auto-merge doesn't trigger
- Ensure branch protection requires status checks
- Verify "Allow auto-merge" is enabled in branch protection
- Check that CI workflows complete successfully

### Workflow doesn't run
- Confirm the PR is from `dependabot[bot]`
- Check the PR targets the `develop` branch
- Verify GitHub Actions are enabled for the repository

### Permission errors
- Ensure the `GITHUB_TOKEN` has sufficient permissions
- Check that workflow permissions are correctly set

## Security Considerations

- **CI must pass**: Auto-merge only happens after all CI checks pass
- **No major updates**: Breaking changes require manual review
- **Audit logs**: All auto-merges are logged in GitHub's audit trail
- **Revert capability**: Can always revert merged PRs if issues arise

## Related Files

- [`.github/workflows/dependabot-auto-merge.yml`](../.github/workflows/dependabot-auto-merge.yml) - Auto-merge workflow
- [`.github/dependabot.yml`](../.github/dependabot.yml) - Dependabot configuration
- [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) - CI checks that must pass

## References

- [GitHub Actions: Automating Dependabot](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/automating-dependabot-with-github-actions)
- [Dependabot Fetch Metadata Action](https://github.com/dependabot/fetch-metadata)
- [Auto-merge Pull Requests](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)
