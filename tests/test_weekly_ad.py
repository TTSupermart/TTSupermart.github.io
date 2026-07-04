from __future__ import annotations

import importlib.util
import io
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pypdf import PdfWriter


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "fetch_weekly_ad.py"
SPEC = importlib.util.spec_from_file_location("fetch_weekly_ad", SCRIPT_PATH)
assert SPEC and SPEC.loader
fetch_weekly_ad = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch_weekly_ad)


def make_pdf(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=2166, height=4444)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


class WeeklyAdSelectionTests(unittest.TestCase):
    def test_target_is_upcoming_ad_week_in_denver(self) -> None:
        now = datetime(2026, 7, 4, 9, 0, tzinfo=ZoneInfo("America/Denver"))
        self.assertEqual(fetch_weekly_ad.target_week_number(now), 28)

    def test_newer_future_week_does_not_replace_target_week(self) -> None:
        four_page_pdf = make_pdf(4)
        candidates = [
            {
                "subject": "Fwd: WK29 Web Ad",
                "received_at": 300.0,
                "weeks": [29],
                "attachments": [("wk29.pdf", four_page_pdf)],
            },
            {
                "subject": "Fwd: WK28 Web Ad",
                "received_at": 200.0,
                "weeks": [28],
                "attachments": [("wk28.pdf", four_page_pdf)],
            },
        ]

        _, subject, filename, week = fetch_weekly_ad.select_pdf(candidates, 28)

        self.assertEqual(subject, "Fwd: WK28 Web Ad")
        self.assertEqual(filename, "wk28.pdf")
        self.assertEqual(week, "WK28")

    def test_missing_target_week_fails_instead_of_using_future_week(self) -> None:
        candidates = [
            {
                "subject": "Fwd: WK29 Web Ad",
                "received_at": 300.0,
                "weeks": [29],
                "attachments": [("wk29.pdf", make_pdf(4))],
            }
        ]

        with self.assertRaisesRegex(fetch_weekly_ad.WeeklyAdError, "target week WK28"):
            fetch_weekly_ad.select_pdf(candidates, 28)

    def test_four_pdf_pages_render_to_four_jpegs(self) -> None:
        images = fetch_weekly_ad.render_pdf_pages(make_pdf(4))

        self.assertEqual(len(images), 4)
        for image in images:
            self.assertTrue(image.startswith(b"\xff\xd8"))
            self.assertTrue(image.endswith(b"\xff\xd9"))


if __name__ == "__main__":
    unittest.main()
