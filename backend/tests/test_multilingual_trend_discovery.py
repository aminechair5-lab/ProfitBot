import unittest
from unittest.mock import patch

from app.main import google_trend_signals


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self.payload


class FakeDB:
    def __init__(self):
        self.rows = []

    def scalar(self, _query):
        return None

    def add(self, row):
        self.rows.append(row)

    def commit(self):
        pass


class MultilingualTrendDiscoveryTests(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_classifies_localized_product_phrases_and_keeps_unknown_titles(self, urlopen):
        titles = [
            "Meilleur aspirateur robot",
            "Heißluftfritteuse Test",
            "Freidora de aire precio",
            "ロボット掃除機 おすすめ",
            "Football match result tonight",
            "Local election results",
        ]
        items = "".join(
            f"<item><title>{title}</title><link>https://example.test/{index}</link></item>"
            for index, title in enumerate(titles)
        )
        payload = f'<?xml version="1.0"?><rss><channel>{items}</channel></rss>'.encode()
        urlopen.return_value = FakeResponse(payload)

        result = google_trend_signals(geo="FR", db=FakeDB())

        matched_titles = [item["title"] for item in result["items"]]
        self.assertIn("Meilleur aspirateur robot", matched_titles)
        self.assertIn("Heißluftfritteuse Test", matched_titles)
        self.assertIn("Freidora de aire precio", matched_titles)
        self.assertIn("ロボット掃除機 おすすめ", matched_titles)
        self.assertNotIn("Football match result tonight", matched_titles)
        self.assertNotIn("Local election results", matched_titles)
        self.assertEqual(result["scanned_count"], 6)
        self.assertEqual(result["unclassified_count"], 2)
        self.assertEqual(len(result["unclassified_items"]), 2)
        self.assertTrue(all(item["commercially_verified"] is False for item in result["items"]))

    def test_algeria_remains_excluded(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):
            google_trend_signals(geo="DZ", db=FakeDB())


if __name__ == "__main__":
    unittest.main()
