#!/usr/bin/env python3
"""Send a weekly ad workflow summary email using Gmail."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any


TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
SUMMARY_PATH = Path("work/weekly-ad-summary.json")


class NotificationError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise NotificationError(f"Missing required environment variable: {name}")
    return value


def request_json(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    data: bytes | dict[str, str] | None = None,
    content_type: str = "application/json",
) -> dict[str, Any]:
    body: bytes | None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        body = data
        if data is not None:
            headers["Content-Type"] = content_type

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise NotificationError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise NotificationError(f"Request failed for {url}: {exc.reason}") from exc


def get_access_token() -> str:
    response = request_json(
        TOKEN_URL,
        method="POST",
        data={
            "client_id": require_env("GOOGLE_CLIENT_ID"),
            "client_secret": require_env("GOOGLE_CLIENT_SECRET"),
            "refresh_token": require_env("GOOGLE_REFRESH_TOKEN"),
            "grant_type": "refresh_token",
        },
    )
    access_token = response.get("access_token")
    if not access_token:
        raise NotificationError("Google OAuth response did not include an access token.")
    return access_token


def load_summary() -> dict[str, Any]:
    if not SUMMARY_PATH.exists():
        return {
            "status": "failed",
            "attachment_filename": None,
            "gmail_subject": None,
            "output_path": "images/weekly-ad.pdf",
            "issues": ["The Gmail download step did not create a summary file."],
        }
    return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))


def build_body(summary: dict[str, Any]) -> str:
    issues = list(summary.get("issues") or [])
    commit_status = os.environ.get("COMMIT_STATUS", "not-run")
    pdf_changed = os.environ.get("PDF_CHANGED", "unknown")
    commit_sha = os.environ.get("COMMIT_SHA", "")
    run_url = os.environ.get("GITHUB_RUN_URL", "")

    if commit_status == "failed":
        issues.append("The PDF was downloaded, but the commit or push step failed.")
    elif summary.get("status") == "success" and commit_status == "skipped":
        issues.append("The commit step was skipped.")

    issue_text = "\n".join(f"- {issue}" for issue in issues) if issues else "- None"
    changed_text = {
        "true": "Yes",
        "false": "No",
    }.get(pdf_changed, pdf_changed)

    lines = [
        "Weekly ad upload summary",
        "",
        f"Download status: {summary.get('status', 'unknown')}",
        f"Gmail attachment found: {summary.get('attachment_filename') or 'None'}",
        f"Gmail subject: {summary.get('gmail_subject') or 'None'}",
        f"Saved path: {summary.get('output_path') or 'images/weekly-ad.pdf'}",
        f"PDF changed: {changed_text}",
        f"Commit status: {commit_status}",
    ]
    if commit_sha:
        lines.append(f"Commit: {commit_sha}")
    if run_url:
        lines.append(f"Workflow run: {run_url}")
    lines.extend(["", "Issues:", issue_text])
    return "\n".join(lines)


def send_email(token: str, subject: str, body: str) -> None:
    profile = request_json(PROFILE_URL, token=token)
    sender = profile.get("emailAddress")
    if not sender:
        raise NotificationError("Could not determine the Gmail sender address.")

    message = EmailMessage()
    message["To"] = require_env("NOTIFICATION_EMAIL")
    message["From"] = sender
    message["Subject"] = subject
    message.set_content(body)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    payload = json.dumps({"raw": raw}).encode("utf-8")
    request_json(SEND_URL, method="POST", token=token, data=payload)


def main() -> int:
    try:
        summary = load_summary()
        body = build_body(summary)
        status = summary.get("status", "unknown")
        commit_status = os.environ.get("COMMIT_STATUS", "not-run")
        subject = f"TTSupermart weekly ad upload: {status}, commit {commit_status}"
        send_email(get_access_token(), subject, body)
        print("Sent weekly ad upload notification.")
        return 0
    except NotificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
