# TTSupermart.github.io

## Weekly ad automation

The `Update weekly ad PDF` GitHub Actions workflow runs every Thursday at 8:07 AM America/Denver and can also be run manually from the Actions tab. GitHub schedules are UTC-only, so the workflow includes both possible UTC times for Denver daylight and standard time, then skips unless the runner sees Thursday 8:07 AM in `America/Denver`.

The workflow signs in to Gmail using IMAP over SSL, searches for emails whose subject contains `Web Ad`, and considers only messages with a PDF attachment. Ads run Thursday through Wednesday. The target week is the ISO week number of the Thursday that begins the active ad period. For example, July 2-8, 2026 is `WK27`; the workflow selects only a `WK27` email and rejects newer `WK28` or `WK29` mail. The selected PDF must have exactly 4 pages.

The PDF is saved to `images/weekly-ad.pdf`, and its four pages are rendered to the JPG files displayed by `weekly-ad.html`. The PDF and JPGs are committed to `main` only when the PDF contents changed.

After each real Wednesday run, the workflow sends a summary to the Gmail account using SMTP over SSL. The summary includes the attachment filename, week indicator, whether the PDF changed, commit status, and any issues. Notification delivery is non-critical: an SMTP failure is logged but does not turn an otherwise successful PDF update into a failed workflow.

### Gmail setup

1. Turn on 2-Step Verification for the Gmail account that receives the weekly ad.
2. Create a Gmail App Password for the workflow. In the Google Account, open **Security > App passwords**, create an app password (for example, named `GitHub Actions`), and copy the generated 16-character password.
3. Make sure IMAP access is allowed for the account. For a managed Google Workspace account, the administrator must also allow IMAP access and App Passwords.
4. Add the two secrets below to the GitHub repository.

The workflow connects to `imap.gmail.com` on port 993 and `smtp.gmail.com` on port 465 using SSL. It does not require a Google Cloud project, Gmail API access, OAuth credentials, or refresh tokens.

### Required GitHub Secrets

Add these repository secrets in GitHub under **Settings > Secrets and variables > Actions**:

- `GMAIL_ADDRESS`: Full Gmail address used to read the weekly ad and receive the workflow notification.
- `GMAIL_APP_PASSWORD`: The App Password generated for that Gmail account. Do not use the account's normal password.

The workflow logs search progress, selected subjects, attachment names, page counts, commit status, and notification status. It does not print secret values.

### Run manually

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Select **Update weekly ad PDF**.
4. Choose **Run workflow** on the `main` branch.
