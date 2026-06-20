# TTSupermart.github.io

## Weekly ad automation

The `Update weekly ad PDF` GitHub Actions workflow runs every Wednesday at 8:07 AM America/Denver and can also be run manually from the Actions tab. GitHub schedules are UTC-only, so the workflow includes both possible UTC times for Denver daylight and standard time, then skips unless the runner sees Wednesday 8:07 AM in `America/Denver`.

The workflow signs in to Gmail with Google OAuth, searches for the newest email whose subject contains `Web Ad` and has a PDF attachment, prefers subjects with week indicators such as `WK26` or `WK27`, validates that the selected PDF has 4 pages, saves it to `images/weekly-ad.pdf`, and commits to `main` only when the PDF changed. After each real Wednesday run, it sends an email summary with the Gmail attachment filename, whether the PDF changed, commit status, and any issues that occurred.

### Required GitHub Secrets

Add these repository secrets in GitHub under **Settings > Secrets and variables > Actions**:

- `GOOGLE_CLIENT_ID`: OAuth client ID for a Google Cloud OAuth client with Gmail API access.
- `GOOGLE_CLIENT_SECRET`: OAuth client secret for that OAuth client.
- `GOOGLE_REFRESH_TOKEN`: Refresh token authorized for the Gmail mailbox using the Gmail read-only and Gmail send scopes.
- `NOTIFICATION_EMAIL`: Email address that should receive the weekly upload summary.

The workflow logs search progress, selected subjects, attachment names, page counts, commit status, and notification status. It does not print secret values.

### Run manually

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Select **Update weekly ad PDF**.
4. Choose **Run workflow** on the `main` branch.
