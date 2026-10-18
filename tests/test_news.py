import unittest
from unittest.mock import Mock

from services.news import (
    NEWS_SEARCH_URL,
    build_borough_queries,
    fetch_local_articles,
)


class BuildBoroughQueriesTests(unittest.TestCase):
    def test_disambiguates_london_borough_without_postcode_or_or(self):
        queries = build_borough_queries(
            "Westminster",
            search_region="London",
            search_terms=["fire", "pollution", "water"],
        )

        self.assertEqual(
            queries,
            [
                ("fire", "Westminster London fire"),
                ("pollution", "Westminster London pollution"),
                ("water", "Westminster London water"),
            ],
        )
        self.assertTrue(all("postcode" not in query.lower() for _, query in queries))
        self.assertTrue(all(" or " not in query.lower() for _, query in queries))

    def test_deduplicates_region_words_and_rejects_unknown_topics(self):
        self.assertEqual(
            build_borough_queries(
                "City of London",
                search_region="London",
                search_terms=["fire", "fire", "untrusted query"],
            ),
            [("fire", "City of London fire")],
        )

    def test_caps_number_of_topic_queries(self):
        self.assertEqual(
            len(
                build_borough_queries(
                    "Westminster",
                    "London",
                    ["fire", "smoke", "pollution", "water", "flooding"],
                )
            ),
            4,
        )


class FetchLocalArticlesTests(unittest.TestCase):
    def test_fetches_serial_topic_queries_and_preserves_date_provenance(self):
        responses = []
        for article_id, title in (("1", "Westminster fire update"), ("2", "Westminster smoke alert")):
            response = Mock()
            response.json.return_value = {
                "results": [
                    {
                        "id": article_id,
                        "title": title,
                        "description": "<p>Council notice &amp; smoke</p><script>bad prompt</script>",
                        "url": f"https://council.example/{article_id}",
                        "sitename": "Westminster Council",
                        "host": "council.example",
                        "published_at": "2026-10-10T12:00:00Z",
                        "date_source": "jsonld",
                        "crawled_at": "2026-10-10T12:05:00Z",
                        "lang": "en",
                        "country_source": "publisher",
                    }
                ]
            }
            responses.append(response)
        session = Mock()
        session.get.side_effect = responses

        results = fetch_local_articles(
            "Westminster",
            search_region="London",
            search_terms=["fire", "smoke"],
            session=session,
        )

        self.assertEqual(results["status"], "ok")
        self.assertEqual(len(results["articles"]), 2)
        self.assertEqual(results["articles"][0]["date_source"], "jsonld")
        self.assertEqual(results["articles"][0]["crawled_at"], "2026-10-10T12:05:00Z")
        self.assertEqual(results["articles"][0]["description"], "Council notice & smoke")
        self.assertEqual(session.get.call_count, 2)
        for call in session.get.call_args_list:
            self.assertEqual(call.args[0], NEWS_SEARCH_URL)
            self.assertEqual(call.kwargs["params"]["date"], "30d")
            self.assertIn("Westminster London", call.kwargs["params"]["q"])

    def test_distinguishes_empty_results_from_rate_limited_provider(self):
        empty_response = Mock()
        empty_response.json.return_value = {"results": []}
        empty_session = Mock()
        empty_session.get.return_value = empty_response

        empty = fetch_local_articles(
            "Westminster", search_terms=["fire"], session=empty_session
        )
        self.assertEqual(empty["status"], "empty")

        rate_limited_response = Mock(status_code=429)
        rate_limited_response.raise_for_status.side_effect = __import__(
            "requests"
        ).HTTPError(response=rate_limited_response)
        rate_limited_session = Mock()
        rate_limited_session.get.return_value = rate_limited_response

        unavailable = fetch_local_articles(
            "Westminster", search_terms=["fire"], session=rate_limited_session
        )
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["errors"], ["rate_limited"])


if __name__ == "__main__":
    unittest.main()