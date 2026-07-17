#!/usr/bin/env python3
"""Download the newest four-page weekly ad PDF from Gmail over IMAP."""

from __future__ import annotations

import imaplib
import json
import os
import re
import ssl
import sys
from datetime import date, datetime, timedelta
from email import policy
from email.message import Message
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pymupdf
from pypdf import PdfReader


IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
OUTPUT_PATH = Path("images/weekly-ad.pdf")
IMAGE_OUTPUT_PATHS = (
    Path("images/weekly-ad.jpg"),
    Path("images/weekly-ad-page-2.jpg"),
    Path("images/weekly-ad-page-3.jpg"),
    Path("images/weekly-ad-page-4.jpg"),
)
SUMMARY_PATH = Path("work/weekly-ad-summary.json")
EXPECTED_PAGE_COUNT = 4
IMAGE_WIDTH = 998
DENVER_TIMEZONE = "America/Denver"
WEEK_RE = re.compile(r"\bWK\s*0?(\d{1,2})\b", re.IGNORECASE)
INTERNALDATE_RE = re.compile(rb'INTERNALDATE "([^"]+)"')


class WeeklyAdError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise WeeklyAdError(f"Missing required environment variable: {name}")
    return value


def subject_week_numbers(subject: str) -> list[int]:
    return [
        week
        for match in WEEK_RE.finditer(subject)
        if 1 <= (week := int(match.group(1))) <= 53
    ]


def target_ad_period(now: datetime | None = None) -> tuple[int, date, date]:
    """Return the active Thursday-Wednesday ad week in Denver."""
    timezone = ZoneInfo(DENVER_TIMEZONE)
    if now is None:
        now = datetime.now(timezone)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone)
    else:
        now = now.astimezone(timezone)

    days_since_thursday = (now.weekday() - 3) % 7
    ad_start = now.date() - timedelta(days=days_since_thursday)
    ad_end = ad_start + timedelta(days=6)
    week = ad_start.isocalendar().week
    print(
        f"Target weekly ad is WK{week:02d}, active {ad_start:%Y-%m-%d} through "
        f"{ad_end:%Y-%m-%d} in {DENVER_TIMEZONE}."
    )
    return week, ad_start, ad_end


def connect_to_gmail() -> imaplib.IMAP4_SSL:
    print(f"Connecting to Gmail IMAP over SSL at {IMAP_HOST}:{IMAP_PORT}.")
    try:
        client = imaplib.IMAP4_SSL(
            IMAP_HOST,
            IMAP_PORT,
            ssl_context=ssl.create_default_context(),
        )
        client.login(require_env("GMAIL_ADDRESS"), require_env("GMAIL_APP_PASSWORD"))
        return client
    except (OSError, imaplib.IMAP4.error) as exc:
        raise WeeklyAdError(f"Could not sign in to Gmail IMAP: {exc}") from exc


def all_mail_mailbox(client: imaplib.IMAP4_SSL) -> str | None:
    """Find Gmail's locale-aware All Mail mailbox from its special-use flag."""
    try:
        status, mailboxes = client.list()
    except imaplib.IMAP4.error:
        return None
    if status != "OK" or not mailboxes:
        return None

    for mailbox in mailboxes:
        if mailbox and b"\\All" in mailbox:
            match = re.search(rb'((?:"(?:[^"\\]|\\.)*")|(?:[^ ]+))$', mailbox)
            if match:
                return match.group(1).decode("utf-8", errors="replace")
    return None


def select_search_mailbox(client: imaplib.IMAP4_SSL) -> str:
    candidates = [
        "t-t-affiliated-ad-image",
        all_mail_mailbox(client),
        '"[Gmail]/All Mail"',
        "INBOX",
    ]
    tried: set[str] = set()
    for mailbox in candidates:
        if not mailbox or mailbox in tried:
            continue
        tried.add(mailbox)
        try:
            status, _ = client.select(mailbox, readonly=True)
        except imaplib.IMAP4.error:
            continue
        if status == "OK":
            print(f"Searching mailbox {mailbox} in read-only mode.")
            return mailbox
    raise WeeklyAdError(
        "Could not select the t-t-affiliated-ad-image label, Gmail All Mail, or INBOX for searching."
    )


def internal_timestamp(metadata: bytes) -> float:
    match = INTERNALDATE_RE.search(metadata)
    if not match:
        return 0.0
    try:
        value = match.group(1).decode("ascii")
        return datetime.strptime(value, "%d-%b-%Y %H:%M:%S %z").timestamp()
    except (UnicodeDecodeError, ValueError):
        return 0.0


def fetch_message(client: imaplib.IMAP4_SSL, uid: bytes) -> tuple[Message, float]:
    status, response = client.uid("fetch", uid, "(BODY.PEEK[] INTERNALDATE)")
    if status != "OK" or not response:
        raise WeeklyAdError(f"Gmail IMAP could not fetch message UID {uid.decode()}.")

    for item in response:
        if isinstance(item, tuple) and len(item) >= 2:
            metadata, raw_message = item[0], item[1]
            if isinstance(metadata, bytes) and isinstance(raw_message, bytes):
                message = BytesParser(policy=policy.default).parsebytes(raw_message)
                return message, internal_timestamp(metadata)

    raise WeeklyAdError(f"Gmail IMAP returned no message body for UID {uid.decode()}.")


def pdf_attachments(message: Message) -> list[tuple[str, bytes]]:
    attachments: list[tuple[str, bytes]] = []
    for part in message.walk():
        if part.is_multipart():
            continue

        filename = part.get_filename() or ""
        is_pdf = filename.lower().endswith(".pdf") or part.get_content_type().lower() == "application/pdf"
        is_attachment = part.get_content_disposition() == "attachment" or bool(filename)
        if not is_pdf or not is_attachment:
            continue

        payload = part.get_payload(decode=True)
        if payload:
            attachments.append((filename or "attachment.pdf", payload))
    return attachments


def list_matching_messages(client: imaplib.IMAP4_SSL) -> list[dict[str, Any]]:
    print('Searching Gmail for messages with a subject containing "Web Ad".')
    status, response = client.uid("search", None, "SUBJECT", '"Web Ad"')
    if status != "OK" or not response:
        raise WeeklyAdError("Gmail IMAP search failed.")

    uids = response[0].split()
    if not uids:
        raise WeeklyAdError('No Gmail messages found with a subject containing "Web Ad".')

    candidates: list[dict[str, Any]] = []
    for index, uid in enumerate(reversed(uids), start=1):
        message, received_at = fetch_message(client, uid)
        subject = str(message.get("Subject", ""))
        attachments = pdf_attachments(message)
        weeks = subject_week_numbers(subject)
        print(
            f"Candidate {index}: subject={subject!r}, weeks={weeks or 'none'}, "
            f"pdf_attachments={len(attachments)}"
        )
        if attachments:
            candidates.append(
                {
                    "subject": subject,
                    "received_at": received_at,
                    "weeks": weeks,
                    "attachments": attachments,
                }
            )

    if not candidates:
        raise WeeklyAdError('No "Web Ad" email had a PDF attachment.')
    return candidates


def pdf_page_count(pdf_bytes: bytes) -> int:
    return len(PdfReader(BytesIO(pdf_bytes)).pages)


def select_pdf(candidates: list[dict[str, Any]], target_week: int) -> tuple[bytes, str, str, str]:
    matching_week = sorted(
        (candidate for candidate in candidates if target_week in candidate["weeks"]),
        key=lambda item: item["received_at"],
        reverse=True,
    )

    if not matching_week:
        found_weeks = sorted({week for candidate in candidates for week in candidate["weeks"]})
        found_label = ", ".join(f"WK{week:02d}" for week in found_weeks) if found_weeks else "none"
        raise WeeklyAdError(
            f'No matching "Web Ad" email with a PDF attachment had target week WK{target_week:02d}. '
            f"Week indicators found: {found_label}."
        )

    invalid_attachments: list[str] = []
    for candidate in matching_week:
        for filename, pdf_bytes in candidate["attachments"]:
            print(f"Checking PDF attachment {filename!r} from subject {candidate['subject']!r}.")
            try:
                page_count = pdf_page_count(pdf_bytes)
            except Exception as exc:
                invalid_attachments.append(f"{filename!r} was not a readable PDF ({exc})")
                continue

            print(f"Attachment {filename!r} has {page_count} page(s).")
            if page_count == EXPECTED_PAGE_COUNT:
                return pdf_bytes, candidate["subject"], filename, f"WK{target_week:02d}"
            invalid_attachments.append(f"{filename!r} had {page_count} page(s)")

    details = "; ".join(invalid_attachments)
    raise WeeklyAdError(
        f"No WK{target_week:02d} PDF attachment had exactly {EXPECTED_PAGE_COUNT} pages. Checked: {details}"
    )


def render_pdf_pages(pdf_bytes: bytes) -> list[bytes]:
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.page_count != EXPECTED_PAGE_COUNT:
                raise WeeklyAdError(
                    f"Cannot render weekly ad images: PDF has {document.page_count} pages."
                )

            images: list[bytes] = []
            for page_number, page in enumerate(document, start=1):
                scale = IMAGE_WIDTH / page.rect.width
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale),
                    colorspace=pymupdf.csRGB,
                    alpha=False,
                )
                images.append(pixmap.tobytes("jpeg", jpg_quality=90))
                print(f"Rendered weekly ad page {page_number} at {pixmap.width}x{pixmap.height}.")
            return images
    except WeeklyAdError:
        raise
    except Exception as exc:
        raise WeeklyAdError(f"Could not render weekly ad JPG images: {exc}") from exc


def write_summary(summary: dict[str, Any]) -> None:
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    client: imaplib.IMAP4_SSL | None = None
    target_week: int | None = None
    ad_start: date | None = None
    ad_end: date | None = None
    try:
        target_week, ad_start, ad_end = target_ad_period()
        client = connect_to_gmail()
        select_search_mailbox(client)
        candidates = list_matching_messages(client)
        pdf_bytes, subject, filename, week_indicator = select_pdf(candidates, target_week)
        image_bytes = render_pdf_pages(pdf_bytes)

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_bytes(pdf_bytes)
        for image_path, page_bytes in zip(IMAGE_OUTPUT_PATHS, image_bytes, strict=True):
            image_path.write_bytes(page_bytes)
        write_summary(
            {
                "status": "success",
                "attachment_filename": filename,
                "gmail_subject": subject,
                "output_path": str(OUTPUT_PATH),
                "image_paths": [str(path) for path in IMAGE_OUTPUT_PATHS],
                "target_week": f"WK{target_week:02d}",
                "ad_start": ad_start.isoformat(),
                "ad_end": ad_end.isoformat(),
                "week_indicator": week_indicator,
                "issues": [],
            }
        )
        print(f"Saved {filename!r} and four rendered JPG pages for {week_indicator}.")
        return 0
    except (WeeklyAdError, OSError, imaplib.IMAP4.error) as exc:
        write_summary(
            {
                "status": "failed",
                "attachment_filename": None,
                "gmail_subject": None,
                "output_path": str(OUTPUT_PATH),
                "image_paths": [str(path) for path in IMAGE_OUTPUT_PATHS],
                "target_week": f"WK{target_week:02d}" if target_week else None,
                "ad_start": ad_start.isoformat() if ad_start else None,
                "ad_end": ad_end.isoformat() if ad_end else None,
                "week_indicator": None,
                "issues": [str(exc)],
            }
        )
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            try:
                client.logout()
            except (OSError, imaplib.IMAP4.error):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
