from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from actions import flight_finder, youtube_video


class SavedReportTests(unittest.TestCase):
    def test_flight_url_query_is_preserved(self) -> None:
        url = flight_finder._build_google_flights_url(
            "JFK", "LAX", "2026-12-01", "2026-12-08", 2, "business"
        )
        parsed_url = urlsplit(url)
        query = parse_qs(parsed_url.query)

        self.assertEqual((parsed_url.scheme, parsed_url.netloc),
                         ("https", "www.google.com"))
        self.assertEqual(
            query["q"],
            ["Flights from JFK to LAX on 2026-12-01 returning 2026-12-08"],
        )
        self.assertEqual(query["adults"], ["2"])
        self.assertEqual(query["cabin"], ["3"])

    def test_youtube_play_never_claims_playback_from_open_request(self) -> None:
        with (
            patch.object(
                youtube_video,
                "_scrape_first_video_url",
                return_value="https://www.youtube.com/watch?v=abcdefghijk",
            ),
            patch.object(youtube_video, "_open_url", return_value=True) as open_url,
        ):
            result = youtube_video._handle_play({"query": "synthetic video"}, None)

        self.assertIn("status=unverified", result)
        self.assertIn("playback could not be verified", result)
        self.assertNotIn("Playing:", result)
        open_url.assert_called_once_with(
            "https://www.youtube.com/watch?v=abcdefghijk"
        )

    def test_youtube_play_reports_browser_launch_failure(self) -> None:
        with (
            patch.object(
                youtube_video,
                "_scrape_first_video_url",
                return_value="https://www.youtube.com/watch?v=abcdefghijk",
            ),
            patch.object(youtube_video, "_open_url", return_value=False),
        ):
            result = youtube_video._handle_play({"query": "synthetic video"}, None)

        self.assertIn("status=failed", result)
        self.assertNotIn("Playing:", result)

    def test_flight_report_is_saved_without_opening_a_real_editor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            with (
                patch.object(Path, "home", return_value=home),
                patch.object(flight_finder, "is_windows", return_value=False),
                patch.object(flight_finder, "is_mac", return_value=False),
                patch.object(flight_finder.subprocess, "Popen") as popen,
                patch("builtins.print"),
            ):
                saved_path = Path(
                    flight_finder._save_to_desktop("flight results", "JFK", "LAX")
                )

            self.assertEqual(saved_path.parent.resolve(), (home / "Desktop").resolve())
            self.assertEqual(saved_path.read_text(encoding="utf-8"), "flight results")
            popen.assert_called_once_with(["xdg-open", str(saved_path)])

    def test_youtube_summary_is_saved_without_opening_a_real_editor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            with (
                patch.object(Path, "home", return_value=home),
                patch.object(youtube_video, "is_windows", return_value=False),
                patch.object(youtube_video, "is_mac", return_value=True),
                patch.object(youtube_video.subprocess, "Popen") as popen,
            ):
                saved_path = Path(
                    youtube_video._save_summary(
                        "video summary", "https://example.test/video"
                    )
                )

            self.assertEqual(saved_path.parent.resolve(), (home / "Desktop").resolve())
            self.assertIn("video summary", saved_path.read_text(encoding="utf-8"))
            popen.assert_called_once_with(["open", "-t", str(saved_path)])


if __name__ == "__main__":
    unittest.main()
