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

    def test_unknown_patient_returns_not_found(self):
        response = self.client.get("/patients/2")

        self.assertEqual(response.status_code, 404)

    @patch("app.get_full_risk_profile")
    def test_generates_profiles_only_after_report_submission(
        self, get_full_risk_profile
    ):
        get_full_risk_profile.side_effect = [
            {
                "postcode": postcode,
                "air_quality": {"available": False},
                "planning_flags": {},
                "deprivation": {"available": False},
                "errors": {},
            }
            for postcode in ("SW7 2AZ", "E1 6AN", "M1 1AE")
        ]

        response = self.client.post("/patients/1/report")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Area context", response.data)
        self.assertEqual(get_full_risk_profile.call_count, 3)

    @patch("app.get_full_risk_profile")
    def test_postcode_failure_is_reported_without_exposing_exception(
        self, get_full_risk_profile
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
            {
                "postcode": "M1 1AE",
                "air_quality": {"available": False},
                "planning_flags": {},
                "deprivation": {"available": False},
                "errors": {},
            },
        ]

        response = self.client.post("/patients/1/report")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Some source data could not be retrieved", response.data)
        self.assertNotIn(b"postcode_lookup_failed", response.data)
        self.assertEqual(get_full_risk_profile.call_count, 3)


if __name__ == "__main__":
    unittest.main()