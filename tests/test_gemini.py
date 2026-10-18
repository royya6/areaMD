import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.gemini import (
    GEMINI_CONTEXT_MODEL,
    GEMINI_SUMMARY_MODEL,
    GeminiConfigurationError,
    GeminiProviderError,
    build_article_selection_prompt,
    build_environmental_report,
    build_summary_prompt,
    create_client,
    select_local_articles,
    summarize_environmental_evidence,
    _summary_config,
)


class GeminiPromptTests(unittest.TestCase):
    def test_sdk_client_can_be_constructed_without_network_call(self):
        self.assertIsNotNone(create_client(api_key="offline-test-key").models)

    def test_summary_config_uses_json_response_mode(self):
        self.assertEqual(_summary_config().response_mime_type, "application/json")

    def test_models_are_separated_for_selection_and_summary(self):
        self.assertEqual(GEMINI_CONTEXT_MODEL, "gemini-flash-lite-latest")
        self.assertEqual(GEMINI_SUMMARY_MODEL, "gemini-flash-lite-latest")

    def test_article_prompt_uses_authority_and_only_candidate_metadata(self):
        prompt = build_article_selection_prompt(
            "Westminster",
            [
                {
                    "id": "article-1",
                    "title": "Council reports local fire",
                    "description": "A council statement describes a fire.",
                    "url": "https://council.example/fire",
                    "published_at": "2026-10-10T12:00:00Z",
                    "date_source": "jsonld",
                }
            ],
        )

        self.assertIn("Westminster", prompt)
        self.assertIn("article-1", prompt)
        self.assertIn("do not assess health relevance", prompt.lower())
        self.assertNotIn("SW7", prompt)
        self.assertNotIn("Jane Doe", prompt)

    def test_summary_prompt_forbids_health_claims(self):
        prompt = build_summary_prompt(
            {"addresses": [{"address_type": "Home"}]},
            [{"local_authority": "Westminster", "articles": []}],
        )

        self.assertIn("Do not refer to a patient or person", prompt)
        self.assertIn("Do not add facts", prompt)
        self.assertIn("no web result does not prove no event occurred", prompt.lower())
        self.assertNotIn("Asthma", prompt)


class GeminiCallsTests(unittest.TestCase):
    @patch(
        "services.gemini.create_client",
        side_effect=GeminiConfigurationError("missing key", "api_key_missing"),
    )
    @patch("services.gemini.fetch_local_articles")
    def test_news_retrieval_runs_without_gemini_client(
        self, fetch_local_articles, create_client
    ):
        article = {
            "id": "fire-1",
            "title": "Westminster council fire notice",
            "url": "https://council.example/fire",
            "publisher": "Westminster Council",
            "published_at": "2026-10-10T12:00:00Z",
            "date_source": "jsonld",
        }
        fetch_local_articles.return_value = {
            "local_authority": "Westminster",
            "status": "ok",
            "articles": [article],
            "errors": [],
            "lookback": "30d",
            "queries": ["Westminster London fire"],
        }

        report = build_environmental_report(
            [
                {
                    "address_type": "Home",
                    "profile": {
                        "location": {"local_authority": "Westminster", "in_london": True},
                        "air_quality": {"available": False},
                        "planning_flags": {},
                        "deprivation": {"available": False},
                        "errors": {},
                    },
                }
            ]
        )

        self.assertEqual(report["summary_status"], "fallback")
        context = report["local_context"][0]
        self.assertEqual(context["selection_status"], "not_run")
        self.assertEqual(context["articles"], [article])
        fetch_local_articles.assert_called_once()
        create_client.assert_called_once_with()

    def test_article_selection_returns_only_existing_candidate_ids(self):
        candidates = [
            {
                "id": "fire-1",
                "title": "Council reports local fire",
                "url": "https://council.example/fire",
            },
            {
                "id": "policy-2",
                "title": "Routine planning update",
                "url": "https://council.example/planning",
            },
        ]
        client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: SimpleNamespace(
                    text=json.dumps({"selected_ids": ["fire-1"]})
                )
            )
        )

        self.assertEqual(select_local_articles(client, "Westminster", candidates), [candidates[0]])

    def test_article_selection_rejects_invented_ids(self):
        client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: SimpleNamespace(
                    text=json.dumps({"selected_ids": ["invented"]})
                )
            )
        )

        with self.assertRaisesRegex(GeminiProviderError, "unknown ID"):
            select_local_articles(
                client,
                "Westminster",
                [{"id": "known", "title": "Notice", "url": "https://example.test/"}],
            )

    def test_search_failure_does_not_prevent_summary_or_send_identifiers(self):
        class FakeModels:
            def __init__(self):
                self.prompts = []

            def generate_content(self, **kwargs):
                self.prompts.append(kwargs["contents"])
                return SimpleNamespace(
                    text=json.dumps(
                        {
                            "overview": "Environmental dataset information is available.",
                            "observations": [],
                            "limitations": ["No local articles were selected."],
                        }
                    )
                )

        profile = {
            "postcode": "SW7 2AZ",
            "location": {
                "postcode": "SW7 2AZ",
                "latitude": 51.5,
                "longitude": -0.12,
                "local_authority": "Westminster",
                "in_london": True,
            },
            "air_quality": {"available": False},
            "planning_flags": {},
            "deprivation": {"available": False},
            "errors": {},
        }
        models = FakeModels()
        client = SimpleNamespace(models=models)

        with patch(
            "services.gemini.fetch_local_articles",
            return_value={
                "local_authority": "Westminster",
                "status": "unavailable",
                "articles": [],
                "errors": ["rate_limited"],
                "lookback": "30d",
                "queries": ["Westminster London fire"],
            },
        ):
            report = build_environmental_report(
                [{"address_type": "Home", "profile": profile}],
                client=client,
            )

        self.assertEqual(report["summary_status"], "generated")
        self.assertEqual(report["local_context"][0]["status"], "unavailable")
        self.assertEqual(len(models.prompts), 1)
        for prompt in models.prompts:
            self.assertNotIn("SW7 2AZ", prompt)
            self.assertNotIn("51.5", prompt)
            self.assertNotIn("-0.12", prompt)
            self.assertNotIn("Jane Doe", prompt)
            self.assertNotIn("asthma", prompt.lower())

    def test_multiple_addresses_in_authority_search_once(self):
        profile = {
            "location": {
                "postcode": "SW7 2AZ",
                "latitude": 51.5,
                "longitude": -0.12,
                "local_authority": "Westminster",
                "in_london": True,
            },
            "air_quality": {"available": False},
            "planning_flags": {},
            "deprivation": {"available": False},
            "errors": {},
        }
        client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: SimpleNamespace(
                    text=json.dumps(
                        {
                            "overview": "Environmental data is available.",
                            "observations": [],
                            "limitations": [],
                        }
                    )
                )
            )
        )

        with patch(
            "services.gemini.fetch_local_articles",
            return_value={
                "local_authority": "Westminster",
                "status": "empty",
                "articles": [],
                "errors": [],
                "lookback": "30d",
                "queries": [],
            },
        ) as fetch_articles:
            report = build_environmental_report(
                [
                    {"address_type": "Home", "profile": profile},
                    {"address_type": "Work", "profile": profile},
                ],
                client=client,
            )

        fetch_articles.assert_called_once_with(
            "Westminster",
            search_region="London",
            search_terms=["fire", "pollution", "smoke", "water"],
            session=None,
        )
        self.assertEqual(report["summary_status"], "generated")

    def test_summary_rejects_patient_health_claims(self):
        client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: SimpleNamespace(
                    text=json.dumps(
                        {
                            "overview": "This creates a health risk for the patient.",
                            "observations": [],
                            "limitations": [],
                        }
                    )
                )
            )
        )

        with self.assertRaises(GeminiProviderError):
            summarize_environmental_evidence(client, {"addresses": []}, [])


if __name__ == "__main__":
    unittest.main()