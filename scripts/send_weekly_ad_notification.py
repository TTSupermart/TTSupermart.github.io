#!/usr/bin/env python3
"""Send a weekly ad workflow summary email through Gmail SMTP."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SUMMARY_PATH = Path("work/weekly-ad-summary.json")


class NotificationError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise NotificationError(f"Missing required environment variable: {name}")
    return value


def load_summary() -> dict[str, Any]:
    if not SUMMARY_PATH.exists():
        return {
            "status": "failed",
            "attachment_filename": None,
            "gmail_subject": None,
            "output_path": "images/weekly-ad.pdf",
            "week_indicator": None,
            "issues": ["The Gmail download step did not create a summary file."],
        }
    return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))


def build_body(summary: dict[str, Any]) -> str:
    issues = list(summary.get("issues") or [])
    commit_status = os.environ.get("COMMIT_STATUS") or "not-run"
    pdf_changed = os.environ.get("PDF_CHANGED") or "unknown"
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
        f"Week indicator: {summary.get('week_indicator') or 'None'}",
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


def send_email(subject: str, body: str) -> None:
    sender = require_env("GMAIL_ADDRESS")
    password = require_env("GMAIL_APP_PASSWORD")

    message = EmailMessage()
    message["To"] = sender
    message["From"] = sender
    message["Subject"] = subject
    message.set_content(body)

    print(f"Connecting to Gmail SMTP over SSL at {SMTP_HOST}:{SMTP_PORT}.")
    try:
        with smtplib.SMTP_SSL(
            SMTP_HOST,
            SMTP_PORT,
            context=ssl.create_default_context(),
            timeout=60,
        ) as smtp:
            smtp.login(sender, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise NotificationError(f"Could not send the Gmail SMTP notification: {exc}") from exc


def main() -> int:
    try:
        summary = load_summary()
        body = build_body(summary)
        status = summary.get("status", "unknown")
        commit_status = os.environ.get("COMMIT_STATUS") or "not-run"
        subject = f"TTSupermart weekly ad upload: {status}, commit {commit_status}"
        send_email(subject, body)
        print("Sent weekly ad upload notification.")
        return 0
    except (NotificationError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
