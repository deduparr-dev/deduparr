# GitHub App Setup for Dependabot Auto-Rebase

This guide explains how to create and configure a GitHub App to enable the Dependabot Auto-Rebase workflow.

## Why a GitHub App?

Dependabot commands (like `@dependabot rebase`) only work when issued by users or GitHub Apps with push access, not by GitHub Actions using the default `GITHUB_TOKEN`. A GitHub App provides the necessary authentication.

## Setup Steps

### 1. Create a GitHub App

1. Navigate to your organization settings: https://github.com/organizations/deduparr-dev/settings/apps
   - Or for personal repos: https://github.com/settings/apps
2. Click **"New GitHub App"**
3. Fill in the details:
   - **GitHub App name**: `Dependabot Rebase Bot` (must be unique)
   - **Homepage URL**: `https://github.com/deduparr-dev/deduparr`
   - **Webhook**: Uncheck **"Active"** (not needed)
   - **Permissions**:
     - Repository permissions:
       - **Pull requests**: Read and write
       - **Contents**: Read-only
       - **Metadata**: Read-only (automatically selected)
   - **Where can this GitHub App be installed?**: Select **"Only on this account"**
4. Click **"Create GitHub App"**

### 2. Generate Private Key

1. After creating the app, scroll down to **"Private keys"**
2. Click **"Generate a private key"**
3. A `.pem` file will download automatically
4. **Keep this file secure** - you'll need it in the next step

### 3. Install the App on Your Repository

1. On the GitHub App page, click **"Install App"** in the left sidebar
2. Select your organization (`deduparr-dev`)
3. Choose **"Only select repositories"**
4. Select `deduparr`
5. Click **"Install"**

### 4. Add Secrets to Repository

1. Note your **App ID** from the GitHub App settings page (top of the page)
2. Go to your repository settings: https://github.com/deduparr-dev/deduparr/settings/secrets/actions
3. Click **"New repository secret"** and add:
   - **Name**: `DEPENDABOT_REBASE_APP_ID`
   - **Value**: Your App ID (e.g., `123456`)
4. Click **"New repository secret"** again and add:
   - **Name**: `DEPENDABOT_REBASE_APP_PRIVATE_KEY`
   - **Value**: Paste the entire contents of the `.pem` file (including `-----BEGIN RSA PRIVATE KEY-----` and `-----END RSA PRIVATE KEY-----`)

### 5. Test the Workflow

1. Go to **Actions** → **Dependabot Auto-Rebase**
2. Click **"Run workflow"**
3. The workflow should now successfully comment on Dependabot PRs

## Security Notes

- The private key is sensitive - treat it like a password
- The app only has access to the repositories you explicitly install it on
- You can revoke the app's access at any time from the installation settings
- The private key can be regenerated if compromised (old keys are invalidated)

## Troubleshooting

### "Resource not accessible by integration"
- Check that the app has **Pull requests: Read and write** permission
- Verify the app is installed on the correct repository
- Ensure the secrets are correctly named and contain valid values

### "Bad credentials"
- The private key format might be incorrect - ensure you copied the entire `.pem` file
- The App ID might be wrong - double-check it matches the GitHub App settings

### Dependabot still rejects commands
- Verify the GitHub App is actually making the comment (check the comment author)
- Ensure the app has push access to the repository (should be automatic with installation)

## References

- [GitHub Apps Documentation](https://docs.github.com/en/apps)
- [Creating a GitHub App](https://docs.github.com/en/apps/creating-github-apps/creating-github-apps/creating-a-github-app)
- [actions/create-github-app-token](https://github.com/actions/create-github-app-token)
