from __future__ import annotations

import builtins
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from actions import web_search
from core import outcome


class WebSearchDependencyTests(unittest.TestCase):
    def test_missing_supported_package_has_actionable_error(self) -> None:
        original_import = builtins.__import__

        def import_without_ddgs(name, *args, **kwargs):
            if name == "ddgs":
                raise ImportError("simulated missing dependency")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_ddgs):
            with self.assertRaisesRegex(RuntimeError, "requires the 'ddgs' package"):
                web_search._get_ddgs()

    def test_empty_ddg_news_does_not_fall_back_to_general_text(self) -> None:
        calls = []

        class FakeDDGS:
            def __init__(self, timeout):
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def news(self, query, max_results, timelimit, region):
                calls.append(("news", timelimit, region, self.timeout))
                return []

            def text(self, query, max_results, timelimit, region):
                calls.append(("text", timelimit, region))
                return []

        with patch.object(web_search, "_get_ddgs", return_value=FakeDDGS):
            self.assertEqual(
                web_search._ddg_news(
                    "noticias Tacna", timelimit="w", region="pe-es"
                ),
                [],
            )

        self.assertEqual(calls, [("news", "w", "pe-es", 3)])

    def test_spanish_local_news_are_recent_and_scoped_to_the_request(self) -> None:
        calls = []

        def fake_news(query, max_results, timelimit, region):
            calls.append((query, timelimit, region))
            return [{
                "title": "Noticia de prueba",
                "snippet": "Un resumen suficientemente largo para validar el resultado de noticias.",
                "url": "https://example.test/news",
                "source": "Fuente",
                "date": "2 hours ago",
            }]

        with patch.object(web_search, "_ddg_news", side_effect=fake_news):
            result = web_search._news(
                "noticias desde el Perú y noticias en Tacna",
                location="Tacna, Peru",
                language="es",
            )

        self.assertIn("NOTICIAS LOCALES Y NACIONALES", result)
        self.assertIn("Últimas 24 horas", result)
        self.assertIn("Fuente: Fuente", result)
        self.assertNotIn("NOTICIAS INTERNACIONALES", result)
        self.assertNotIn("https://", result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1:], ("d", "pe-es"))
        self.assertIn("Tacna", calls[0][0])
        self.assertIn("Perú", calls[0][0])
        self.assertEqual(calls[0][0].count("Tacna"), 1)

    def test_old_headlines_are_rejected_then_weekly_results_are_labeled(self) -> None:
        calls = []

        def fake_news(query, max_results, timelimit, region):
            calls.append(timelimit)
            return [{
                "title": f"Noticia {timelimit}",
                "source": "Fuente",
                "url": f"https://example.test/{timelimit}",
                "date": "3 days ago" if timelimit == "w" else "3 days ago",
            }]

        with patch.object(web_search, "_ddg_news", side_effect=fake_news):
            result = web_search._news(
                "noticias Tacna", location="Tacna, Peru", language="es"
            )

        self.assertEqual(calls, ["d", "w"])
        self.assertIn("Últimos 7 días", result)
        self.assertIn("Noticia w", result)
        self.assertNotIn("Noticia d", result)

    def test_news_without_verifiable_dates_is_not_called_recent(self) -> None:
        with patch.object(
            web_search,
            "_ddg_news",
            return_value=[{
                "title": "Titular sin fecha",
                "url": "https://example.test/old",
                "source": "Fuente",
            }],
        ):
            result = web_search._news(
                "noticias Tacna", location="Tacna, Peru", language="es"
            )

        self.assertTrue(result.startswith("No pude verificar noticias recientes"))
        self.assertNotIn("Titular sin fecha", result)

    def test_recent_news_is_sorted_deduplicated_and_date_checked(self) -> None:
        now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        results = [
            {"title": "Older", "url": "https://example.test/older", "date": "20 hours ago"},
            {"title": "Newer", "url": "https://example.test/newer", "date": "1 hour ago"},
            {"title": "Duplicate", "url": "https://example.test/newer", "date": "2 hours ago"},
            {"title": "Too old", "url": "https://example.test/old", "date": "3 days ago"},
            {"title": "Unknown date", "url": "https://example.test/unknown"},
        ]

        recent = web_search._filter_recent_news(
            results, timedelta(days=1), now=now
        )

        self.assertEqual([item["title"] for item in recent], ["Newer", "Older"])

    def test_dispatch_wrapper_is_not_nested_for_search_results(self) -> None:
        content = "NOTICIAS\nTitular de prueba"
        with (
            patch.object(web_search, "_search", return_value=content),
            patch("builtins.print"),
        ):
            raw = web_search.web_search({"query": "prueba"})

        normalized = outcome.normalize_dispatch_result("web_search", raw)
        display = outcome.unwrap(normalized)
        self.assertEqual(display.strip(), "NOTICIAS Titular de prueba")
        self.assertNotIn("<<<UNTRUSTED source=web>>>", display)


if __name__ == "__main__":
    unittest.main()
