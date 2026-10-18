import unittest
from unittest.mock import patch

from app import create_app
from services.risk_profile import RiskProfileError


class AppRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
        self.client = self.app.test_client()

    @patch("app.get_full_risk_profile")
    def test_login_and_patient_list_render_without_provider_calls(
        self, get_full_risk_profile
    ):
        login_response = self.client.get("/")
        list_response = self.client.get("/patients")

        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.location, "/patients")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn(b"Demo Patient", list_response.data)
        self.assertIn(b"Search patients", list_response.data)
        get_full_risk_profile.assert_not_called()

    def test_doctor_login_is_visible_but_not_implemented(self):
        response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Doctor login", response.data)
        self.assertIn(b"not available yet", response.data)

    @patch("app.get_full_risk_profile")
    def test_patient_page_does_not_fetch_profiles(self, get_full_risk_profile):
        response = self.client.get("/patients/1")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Demo Patient", response.data)
        self.assertIn(b"1980-01-12", response.data)
        self.assertIn(b"Save details", response.data)
        self.assertIn(b"Add address", response.data)
        self.assertIn(b"Past reports", response.data)
        self.assertNotIn(b"Synthetic demo record", response.data)
        self.assertIn(b"Generate report", response.data)
        get_full_risk_profile.assert_not_called()

    def test_edit_patient_updates_demo_record(self):
        response = self.client.post(
            "/patients/1/edit",
            data={
                "name": "Updated Demo",
                "dob": "1981-02-03",
                "conditions": "Asthma, Example condition",
            },
        )

        self.assertEqual(response.status_code, 302)
        detail = self.client.get("/patients/1")
        self.assertIn(b"Updated Demo", detail.data)
        self.assertIn(b"1981-02-03", detail.data)

    def test_add_and_edit_address(self):
        add_response = self.client.post(
            "/patients/1/addresses",
            data={"address_type": "Work", "postcode": "  ec1a 1bb "},
        )

        self.assertEqual(add_response.status_code, 302)
        self.assertIn("EC1A 1BB", self.app.config["MOCK_PATIENTS"][0]["addresses"][-1]["postcode"])

        edit_response = self.client.post(
            "/patients/1/addresses/1/edit",
            data={"address_type": "Home", "postcode": "W1A 1AA"},
        )

        self.assertEqual(edit_response.status_code, 302)
        self.assertEqual(self.app.config["MOCK_PATIENTS"][0]["addresses"][0]["postcode"], "W1A 1AA")

    def test_past_report_link_opens_demo_report(self):
        response = self.client.get("/patients/1/reports/1")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Example appointment", response.data)
        self.assertIn(b"Sample report only", response.data)
        self.assertEqual(response.data.count(b"Sample report only"), 1)
        self.assertIn(b"not a saved clinical record", response.data)

    def test_fallback_report_opens_source_details(self):
        self.app.config["MOCK_REPORTS"].append(
            {
                "id": 2,
                "patient_id": 1,
                "appointment_date": "2026-10-17",
                "appointment_label": "Environmental report",
                "summary_text": "Summary unavailable.",
                "summary_data": {"overview": "Summary unavailable."},
                "summary_status": "fallback",
                "summary_issue_message": "The request failed.",
                "local_context": [],
                "environmental_evidence": {
                    "addresses": [
                        {
                            "address_type": "Home",
                            "local_authority": "Westminster",
                            "evidence": [],
                        }
                    ]
                },
            }
        )

        response = self.client.get("/patients/1/reports/2")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"The request failed.", response.data)
        self.assertIn(b'<summary>Data quality and source details</summary>', response.data)
        self.assertIn(b'<details class="report-sources" open>', response.data)

    def test_report_can_show_unscreened_news_candidates(self):
        self.app.config["MOCK_REPORTS"].append(
            {
                "id": 3,
                "patient_id": 1,
                "appointment_date": "2026-10-17",
                "appointment_label": "Environmental report",
                "summary_text": "Summary unavailable.",
                "summary_data": {"overview": "Summary unavailable."},
                "summary_status": "fallback",
                "local_context": [
                    {
                        "local_authority": "Westminster",
                        "status": "ok",
                        "lookback": "30d",
                        "selection_status": "not_run",
                        "articles": [
                            {
                                "url": "https://council.example/fire",
                                "title": "Council fire notice",
                                "publisher": "Westminster Council",
                                "published_at": "2026-10-10T12:00:00Z",
                                "date_source": "jsonld",
                            }
                        ],
                    }
                ],
                "environmental_evidence": {"addresses": []},
            }
        )

        response = self.client.get("/patients/1/reports/3")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"not relevance-screened", response.data)
        self.assertIn(b"https://council.example/fire", response.data)

    def test_unknown_patient_returns_not_found(self):
        response = self.client.get("/patients/999")

        self.assertEqual(response.status_code, 404)

    @patch("app.build_environmental_report")
    @patch("app.get_full_risk_profile")
    def test_generates_and_saves_report_for_home_and_work_only(
        self, get_full_risk_profile, build_environmental_report
    ):
        get_full_risk_profile.side_effect = [
            {
                "postcode": postcode,
                "air_quality": {"available": False},
                "planning_flags": {},
                "deprivation": {"available": False},
                "errors": {},
            }
            for postcode in ("SW7 2AZ", "E1 6AN")
        ]
        build_environmental_report.return_value = {
            "summary_text": "An environmental summary.",
            "summary_data": {
                    "overview": "An environmental summary.",
                    "observations": ["A source lists a local incident."],
                    "limitations": ["Location is reported at local-authority scale."],
                },
            "summary_status": "generated",
            "environmental_evidence": {
                "addresses": [
                    {
                        "address_type": "Home",
                        "local_authority": "Westminster",
                        "evidence": [
                            {
                                "topic": "nearest_monitoring_site",
                                "state": "available",
                                "facts": {"site_name": "Example monitor"},
                                "source": "London Air Quality Network",
                                "reliability_context": {
                                    "freshness": "date unavailable",
                                    "geographic_scope": "nearest monitor",
                                    "directness": "site metadata only",
                                    "coverage": "London sites",
                                    "limitations": ["Not an address-level measurement."],
                                },
                            }
                        ],
                    }
                ]
            },
            "local_context": [],
        }

        response = self.client.post("/patients/1/report", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"An environmental summary", response.data)
        self.assertIn(b"A source lists a local incident", response.data)
        self.assertIn(b"Data limitations:", response.data)
        self.assertIn(b"Data quality and source details", response.data)
        self.assertEqual(get_full_risk_profile.call_count, 2)
        self.assertEqual(build_environmental_report.call_count, 1)
        self.assertEqual(len(self.app.config["MOCK_REPORTS"]), 2)

    @patch("app.build_environmental_report")
    @patch("app.get_full_risk_profile")
    def test_postcode_failure_is_reported_without_exposing_exception(
        self, get_full_risk_profile, build_environmental_report
    ):
        get_full_risk_profile.side_effect = [
            RiskProfileError("postcode_lookup_failed"),
            {
                "postcode": "E1 6AN",
                "air_quality": {"available": False},
                "planning_flags": {},
                "deprivation": {"available": False},
                "errors": {},
            },
        ]
        build_environmental_report.return_value = {
            "summary_text": "An environmental summary.",
            "summary_data": {},
            "summary_status": "generated",
            "environmental_evidence": {"addresses": []},
            "local_context": [],
        }

        response = self.client.post("/patients/1/report", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"postcode_lookup_failed", response.data)
        self.assertEqual(get_full_risk_profile.call_count, 2)


if __name__ == "__main__":
    unittest.main()