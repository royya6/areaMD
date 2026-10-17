import unittest
from unittest.mock import patch

from app import create_app
from db import db
from models import Doctor, Patient
from services.risk_profile import RiskProfileError
from werkzeug.security import generate_password_hash


class AppRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    @patch("app.get_full_risk_profile")
    def test_login_and_patient_list_render_without_provider_calls(
        self, get_full_risk_profile
    ):
        login_response = self.client.get("/")
        list_response = self.client.get("/patients")

        self.assertEqual(login_response.status_code, 200)
        self.assertIn(b"Doctor sign in", login_response.data)
        self.assertIn(b"site-header", login_response.data)
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(list_response.status_code, 200)
        self.assertIn(b"Demo Patient", list_response.data)
        self.assertIn(b"Search patients", list_response.data)
        get_full_risk_profile.assert_not_called()

    def test_doctor_login_rejects_unknown_names_and_wrong_passwords(self):
        with self.app.app_context():
            db.session.add(
                Doctor(
                    name="Dr Example",
                    password_hash=generate_password_hash("correct-password"),
                )
            )
            db.session.add(
                Doctor(
                    name="Legacy Doctor",
                    password_hash="unsupported-method$salt$digest",
                )
            )
            db.session.commit()

        for credentials in (
            {"doctor_name": "Unknown Doctor", "password": "correct-password"},
            {"doctor_name": "Dr Example", "password": "wrong-password"},
            {"doctor_name": "Legacy Doctor", "password": "any-password"},
        ):
            response = self.client.post("/login", data=credentials)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Doctor name or password is incorrect.", response.data)

    def test_valid_doctor_login_redirects_to_patients(self):
        with self.app.app_context():
            doctor = Doctor(
                name="Dr Example",
                password_hash=(
                    generate_password_hash(
                        "correct-password",
                        method="pbkdf2:sha256",
                    )
                    + "\n"
                ),
            )
            db.session.add(doctor)
            db.session.commit()
            doctor_id = doctor.id

        response = self.client.post(
            "/login",
            data={"doctor_name": "dr example", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/patients")
        with self.client.session_transaction() as session_state:
            self.assertEqual(session_state["doctor_id"], doctor_id)

    def test_create_patient_is_persisted_and_visible(self):
        with self.app.app_context():
            doctor = Doctor(
                name="Dr Example",
                password_hash=generate_password_hash("correct-password"),
            )
            db.session.add(doctor)
            db.session.commit()
            doctor_id = doctor.id
        with self.client.session_transaction() as session_state:
            session_state["doctor_id"] = doctor_id

        response = self.client.post(
            "/patients",
            data={
                "name": "New Patient",
                "dob": "1990-05-14",
                "ethnicity": "Other",
                "nhs_number": "123 456 7890",
                "conditions": "Asthma, Example condition",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/patients")
        self.assertIn(b"New Patient", self.client.get("/patients").data)
        with self.app.app_context():
            patient = Patient.query.filter_by(name="New Patient").one()
            self.assertEqual(patient.dob.isoformat(), "1990-05-14")
            self.assertEqual(patient.nhs_number, "1234567890")
            self.assertEqual(patient.doctor_id, doctor_id)
            patient_id = patient.id
        self.assertEqual(self.client.get(f"/patients/{patient_id}").status_code, 200)

    def test_create_patient_rejects_missing_and_malformed_fields(self):
        with self.app.app_context():
            doctor = Doctor(
                name="Dr Example",
                password_hash=generate_password_hash("correct-password"),
            )
            db.session.add(doctor)
            db.session.commit()
            doctor_id = doctor.id
        with self.client.session_transaction() as session_state:
            session_state["doctor_id"] = doctor_id

        valid_data = {
            "name": "New Patient",
            "dob": "1990-05-14",
            "ethnicity": "Other",
            "nhs_number": "",
            "conditions": "Asthma",
        }
        invalid_submissions = (
            {**valid_data, "ethnicity": ""},
            {**valid_data, "dob": "not-a-date"},
            {**valid_data, "nhs_number": "12345abcde"},
        )
        for form_data in invalid_submissions:
            response = self.client.post("/patients", data=form_data)
            self.assertEqual(response.status_code, 400)

        with self.app.app_context():
            self.assertEqual(Patient.query.count(), 0)

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