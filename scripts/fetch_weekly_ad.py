#!/usr/bin/env python3
"""Download the newest weekly ad PDF attachment from Gmail."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pypdf import PdfReader


TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
SEARCH_QUERY = 'subject:"Web Ad" has:attachment filename:pdf'
OUTPUT_PATH = Path("images/weekly-ad.pdf")
SUMMARY_PATH = Path("work/weekly-ad-summary.json")
EXPECTED_PAGE_COUNT = 4
MAX_MESSAGES_TO_CHECK = 50
DENVER_TIMEZONE = "America/Denver"
WEEK_RE = re.compile(r"\bWK\s*0?(\d{1,2})\b", re.IGNORECASE)


class WeeklyAdError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise WeeklyAdError(f"Missing required environment variable: {name}")
    return value


def current_week_number() -> int:
    override = os.environ.get("WEEKLY_AD_WEEK", "").strip()
    if override:
        match = re.fullmatch(r"(?:WK)?\s*0?(\d{1,2})", override, re.IGNORECASE)
        if not match:
            raise WeeklyAdError(f"Invalid WEEKLY_AD_WEEK override: {override!r}. Use a value like WK25 or 25.")
        week = int(match.group(1))
        if not 1 <= week <= 53:
            raise WeeklyAdError(f"Invalid WEEKLY_AD_WEEK override: {override!r}. Week must be 1 through 53.")
        print(f"Using manual weekly ad week override: WK{week:02d}.")
        return week

    now = datetime.now(ZoneInfo(DENVER_TIMEZONE))
    week = now.isocalendar().week
    print(f"Current {DENVER_TIMEZONE} ISO week is WK{week:02d}.")
    return week


def subject_week_numbers(subject: str) -> list[int]:
    return [int(match.group(1)) for match in WEEK_RE.finditer(subject)]


def request_json(url: str, *, method: str = "GET", token: str | None = None, data: dict[str, str] | None = None) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise WeeklyAdError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise WeeklyAdError(f"Request failed for {url}: {exc.reason}") from exc


def get_access_token() -> str:
    print("Requesting Gmail OAuth access token.")
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
        raise WeeklyAdError("Google OAuth response did not include an access token.")
    return access_token


def gmail_get(token: str, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return request_json(f"{GMAIL_API}/{path}{query}", token=token)


def list_matching_messages(token: str) -> list[dict[str, Any]]:
    print(f"Searching Gmail for: {SEARCH_QUERY}")
    messages: list[dict[str, Any]] = []
    page_token: str | None = None

    while len(messages) < MAX_MESSAGES_TO_CHECK:
        params = {"q": SEARCH_QUERY, "maxResults": "10"}
        if page_token:
            params["pageToken"] = page_token

        response = gmail_get(token, "messages", params)
        messages.extend(response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    if not messages:
        raise WeeklyAdError('No Gmail messages found with subject containing "Web Ad" and a PDF attachment.')

    print(f"Found {len(messages)} matching Gmail message(s) to inspect.")
    return messages[:MAX_MESSAGES_TO_CHECK]


def header_value(message: dict[str, Any], name: str) -> str:
    headers = message.get("payload", {}).get("headers", [])
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def iter_parts(part: dict[str, Any]):
    yield part
    for child in part.get("parts", []) or []:
        yield from iter_parts(child)


def pdf_attachment_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    parts = []
    for part in iter_parts(message.get("payload", {})):
        filename = part.get("filename", "")
        body = part.get("body", {})
        mime_type = part.get("mimeType", "")
        if body.get("attachmentId") and (filename.lower().endswith(".pdf") or mime_type == "application/pdf"):
            parts.append(part)
    return parts


def fetch_message_details(token: str, messages: list[dict[str, Any]], target_week: int) -> list[dict[str, Any]]:
    detailed = []
    for index, item in enumerate(messages, start=1):
        message = gmail_get(
            token,
            f"messages/{item['id']}",
            {"format": "full"},
        )
        subject = header_value(message, "Subject")
        internal_date = int(message.get("internalDate", "0"))
        pdf_count = len(pdf_attachment_parts(message))
        weeks = subject_week_numbers(subject)
        target_week_match = target_week in weeks
        print(
            f"Candidate {index}: subject={subject!r}, weeks={weeks or 'none'}, "
            f"target_week_match={target_week_match}, pdf_attachments={pdf_count}"
        )
        detailed.append(
            {
                "message": message,
                "subject": subject,
                "internal_date": internal_date,
                "weeks": weeks,
                "target_week_match": target_week_match,
                "pdf_count": pdf_count,
            }
        )
    return detailed


def decode_gmail_data(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def download_attachment(token: str, message_id: str, attachment_id: str) -> bytes:
    response = gmail_get(token, f"messages/{message_id}/attachments/{attachment_id}")
    data = response.get("data")
    if not data:
        raise WeeklyAdError("Gmail attachment response did not include data.")
    return decode_gmail_data(data)


def pdf_page_count(pdf_bytes: bytes) -> int:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as temp_file:
        temp_file.write(pdf_bytes)
        temp_file.flush()
        return len(PdfReader(temp_file.name).pages)


def write_summary(summary: dict[str, Any]) -> None:
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def select_and_download_pdf(token: str, candidates: list[dict[str, Any]], target_week: int) -> tuple[bytes, str, str]:
    week_candidates = [candidate for candidate in candidates if candidate["target_week_match"]]
    if not week_candidates:
        found_weeks = sorted({week for candidate in candidates for week in candidate["weeks"]})
        found_label = ", ".join(f"WK{week:02d}" for week in found_weeks) if found_weeks else "none"
        raise WeeklyAdError(
            f'No matching "Web Ad" email with a PDF attachment had the current week indicator WK{target_week:02d}. '
            f"Week indicators found: {found_label}."
        )

    sorted_candidates = sorted(
        week_candidates,
        key=lambda item: item["internal_date"],
        reverse=True,
    )

    saw_pdf = False
    for candidate in sorted_candidates:
        message = candidate["message"]
        parts = pdf_attachment_parts(message)
        if not parts:
            continue
        saw_pdf = True

        for part in parts:
            filename = part.get("filename") or "attachment.pdf"
            attachment_id = part["body"]["attachmentId"]
            print(f"Downloading PDF attachment {filename!r} from subject {candidate['subject']!r}.")
            pdf_bytes = download_attachment(token, message["id"], attachment_id)
            try:
                page_count = pdf_page_count(pdf_bytes)
            except Exception as exc:
                raise WeeklyAdError(f"Downloaded attachment {filename!r} is not a readable PDF: {exc}") from exc

            print(f"Attachment {filename!r} has {page_count} page(s).")
            if page_count == EXPECTED_PAGE_COUNT:
                return pdf_bytes, candidate["subject"], filename

    if not saw_pdf:
        raise WeeklyAdError('Matching Gmail messages were found, but none had a PDF attachment.')

    raise WeeklyAdError(
        f"No WK{target_week:02d} PDF attachment had exactly {EXPECTED_PAGE_COUNT} pages."
    )


def main() -> int:
    target_week: int | None = None
    try:
        target_week = current_week_number()
        token = get_access_token()
        messages = list_matching_messages(token)
        candidates = fetch_message_details(token, messages, target_week)
        pdf_bytes, subject, filename = select_and_download_pdf(token, candidates, target_week)

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_bytes(pdf_bytes)
        write_summary(
            {
                "status": "success",
                "attachment_filename": filename,
                "gmail_subject": subject,
                "output_path": str(OUTPUT_PATH),
                "target_week": f"WK{target_week:02d}",
                "issues": [],
            }
        )
        print(f"Saved {filename!r} from subject {subject!r} to {OUTPUT_PATH}.")
        return 0
    except WeeklyAdError as exc:
        write_summary(
            {
                "status": "failed",
                "attachment_filename": None,
                "gmail_subject": None,
                "output_path": str(OUTPUT_PATH),
                "target_week": f"WK{target_week:02d}" if target_week else None,
                "issues": [str(exc)],
            }
        )
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
