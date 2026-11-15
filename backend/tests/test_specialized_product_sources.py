import unittest
from unittest.mock import patch

from app.product_sources import classify_product_coverage, discover_product_articles, normalize


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self.payload


class SpecializedProductSourceTests(unittest.TestCase):
    def test_classifies_product_specific_editorial_titles(self):
        result = classify_product_coverage("Best air fryer reviews: top kitchen gadgets")
        self.assertIsNotNone(result)
        self.assertEqual(result["category"], "Home & Kitchen")
        self.assertIn("air fryer", result["matched_product_terms"])
        self.assertEqual(result["signal_type"], "editorial_product_coverage")
        self.assertEqual(result["confidence"], "low")

    def test_title_normalization_keeps_distinct_product_headlines_distinct(self):
        air_fryer = normalize("Smarte Heißluftfritteusen: Diese Airfryer mit WLAN überzeugen im Test")
        headphones = normalize("Sony wireless headphones return in a new product launch")
        self.assertIn("heissluftfritteusen", air_fryer)
        self.assertIn("airfryer", air_fryer)
        self.assertIn("headphones", headphones)
        self.assertNotEqual(air_fryer, headphones)

    def test_rejects_generic_people_and_sports_headlines(self):
        self.assertIsNone(classify_product_coverage("Josh Downs scores a late touchdown"))
        self.assertIsNone(classify_product_coverage("Missouri vs Marquette live score"))

    def test_requires_shopping_context_even_when_a_product_word_appears(self):
        self.assertIsNone(classify_product_coverage("Air fryer arrives in a new kitchen showroom"))

    def test_rejects_generic_books_and_gift_guides(self):
        self.assertIsNone(classify_product_coverage("Best selling books and gift ideas for the holidays"))

    @patch("app.product_sources.urllib.request.urlopen")
    def test_fetches_market_localized_google_news_rss(self, urlopen):
        payload = (
            '<?xml version="1.0"?><rss><channel>'
            '<item><title>Best air fryer reviews for small kitchens</title>'
            '<link>https://news.example.test/air-fryer</link>'
            '<pubDate>Sun, 15 Nov 2026 10:00:00 GMT</pubDate></item>'
            '<item><title>Josh Downs scores again</title>'
            '<link>https://news.example.test/sports</link></item>'
            '</channel></rss>'
        ).encode()
        urlopen.return_value = FakeResponse(payload)

        result = discover_product_articles("US")

        self.assertEqual(result["scanned_count"], 2)
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["items"][0]["category"], "Home & Kitchen")
        self.assertEqual(result["items"][0]["source_type"], "editorial_coverage")
        self.assertFalse(result["items"][0]["demand_verified"])
        request = urlopen.call_args.args[0]
        self.assertIn("news.google.com/rss/search", request.full_url)
        self.assertIn("gl=US", request.full_url)

    def test_algeria_is_not_a_supported_target_market(self):
        with self.assertRaises(ValueError):
            discover_product_articles("DZ")


if __name__ == "__main__":
    unittest.main()
