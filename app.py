from copy import deepcopy
from datetime import date, datetime, timezone

from flask import Flask, abort, redirect, render_template, request, url_for

from config import Config
from db import db
from services.gemini import build_environmental_report
from services.risk_profile import RiskProfileError, get_full_risk_profile


MOCK_PATIENTS = [
    {
        "id": 1,
        "name": "Demo Patient",
        "dob": "1980-01-12",
        "conditions": ["Sample data only"],
        "addresses": [
            {"id": 1, "type": "Home", "postcode": "SW7 2AZ"},
            {"id": 2, "type": "Work", "postcode": "E1 6AN"},
            {"id": 3, "type": "Previous home", "postcode": "M1 1AE"},
        ],
    },
    {
        "id": 2,
        "name": "Demo Patient · Flood Warning Scenario",
        "dob": "1975-06-20",
        "conditions": ["Demo warning scenario"],
        "addresses": [
            {"id": 4, "type": "Home", "postcode": "E14 5AB"},
            {"id": 5, "type": "Work", "postcode": "E16 1AA"},
        ],
    },
]

MOCK_REPORTS = [
    {
        "id": 1,
        "patient_id": 1,
        "appointment_date": "2026-09-17",
        "appointment_label": "Example appointment",
        "summary_text": "Sample report only. No clinical conclusions or real patient data.",
        "summary_status": "example",
        "local_context": [],
    },
]


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    app.config.setdefault("MOCK_PATIENTS", deepcopy(MOCK_PATIENTS))
    app.config.setdefault("MOCK_REPORTS", deepcopy(MOCK_REPORTS))
    db.init_app(app)

    from models import Doctor, Patient, Address, Report  # noqa

    @app.cli.command("init-db")
    def init_db():
        """Create the relational tables; Timescale hypertables are separate."""
        with app.app_context():
            db.create_all()

    @app.route("/")
    def index():
        return redirect(url_for("patients"))

    @app.route("/login")
    def login():
        return render_template("login.html")

    @app.route("/patients")
    def patients():
        return render_template(
            "patient_list.html",
            patients=app.config["MOCK_PATIENTS"],
        )

    def find_patient(patient_id):
        patient = next(
            (
                item
                for item in app.config["MOCK_PATIENTS"]
                if item["id"] == patient_id
            ),
            None,
        )
        if patient is None:
            abort(404)
        return patient

    def render_patient_detail(patient, profiles=None, form_error=None):
        reports = [
            report
            for report in app.config["MOCK_REPORTS"]
            if report["patient_id"] == patient["id"]
        ]
        return render_template(
            "patient_detail.html",
            patient=patient,
            profiles=profiles,
            reports=reports,
            form_error=form_error,
        )

    @app.route("/patients/<int:patient_id>")
    def patient_detail(patient_id):
        return render_patient_detail(find_patient(patient_id))

    @app.route("/patients/<int:patient_id>/edit", methods=["POST"])
    def edit_patient(patient_id):
        patient = find_patient(patient_id)
        name = request.form.get("name", "").strip()
        dob = request.form.get("dob", "").strip()
        conditions = request.form.get("conditions", "").strip()

        if not name or len(name) > 120 or len(conditions) > 500:
            return render_patient_detail(
                patient,
                form_error="Enter a name and keep the fields within their limits.",
            ), 400
        if dob:
            try:
                date.fromisoformat(dob)
            except ValueError:
                return render_patient_detail(
                    patient,
                    form_error="Enter a valid date of birth.",
                ), 400

        patient["name"] = name
        patient["dob"] = dob
        patient["conditions"] = [
            condition.strip()
            for condition in conditions.split(",")
            if condition.strip()
        ]
        return redirect(url_for("patient_detail", patient_id=patient_id))

    @app.route("/patients/<int:patient_id>/addresses", methods=["POST"])
    def add_address(patient_id):
        patient = find_patient(patient_id)
        address_type = request.form.get("address_type", "").strip()
        postcode = request.form.get("postcode", "").strip().upper()
        allowed_types = {"Home", "Work", "Previous home"}
        if address_type not in allowed_types or not postcode or len(postcode) > 10:
            return render_patient_detail(
                patient,
                form_error="Choose an address type and enter a valid postcode.",
            ), 400

        next_id = max((address["id"] for address in patient["addresses"]), default=0) + 1
        patient["addresses"].append(
            {"id": next_id, "type": address_type, "postcode": postcode}
        )
        return redirect(url_for("patient_detail", patient_id=patient_id))

    @app.route(
        "/patients/<int:patient_id>/addresses/<int:address_id>/edit",
        methods=["POST"],
    )
    def edit_address(patient_id, address_id):
        patient = find_patient(patient_id)
        address = next(
            (item for item in patient["addresses"] if item["id"] == address_id),
            None,
        )
        if address is None:
            abort(404)

        address_type = request.form.get("address_type", "").strip()
        postcode = request.form.get("postcode", "").strip().upper()
        allowed_types = {"Home", "Work", "Previous home"}
        if address_type not in allowed_types or not postcode or len(postcode) > 10:
            return render_patient_detail(
                patient,
                form_error="Choose an address type and enter a valid postcode.",
            ), 400

        address.update({"type": address_type, "postcode": postcode})
        return redirect(url_for("patient_detail", patient_id=patient_id))

    @app.route("/patients/<int:patient_id>/reports/<int:report_id>")
    def previous_report(patient_id, report_id):
        find_patient(patient_id)
        report = next(
            (
                item
                for item in app.config["MOCK_REPORTS"]
                if item["id"] == report_id and item["patient_id"] == patient_id
            ),
            None,
        )
        if report is None:
            abort(404)
        return render_template(
            "report.html",
            patient=find_patient(patient_id),
            report=report,
        )

    @app.route("/patients/<int:patient_id>/report", methods=["POST"])
    def generate_report(patient_id):
        patient = find_patient(patient_id)

        profiles = []
        for address in patient["addresses"]:
            if address["type"] not in {"Home", "Work"}:
                continue
            try:
                profile = get_full_risk_profile(address["postcode"])
            except RiskProfileError:
                profile = {
                    "postcode": address["postcode"],
                    "errors": {"postcode": "lookup_failed"},
                }
            profiles.append({"address_type": address["type"], "profile": profile})

        environmental_report = build_environmental_report(
            profiles,
            client=app.config.get("GEMINI_CLIENT"),
        )
        reports = app.config["MOCK_REPORTS"]
        report_id = max((report["id"] for report in reports), default=0) + 1
        generated_at = datetime.now(timezone.utc)
        reports.append(
            {
                "id": report_id,
                "patient_id": patient_id,
                "appointment_date": generated_at.date().isoformat(),
                "generated_at": generated_at.isoformat(),
                "appointment_label": "Environmental report",
                **environmental_report,
            }
        )
        return redirect(
            url_for(
                "previous_report",
                patient_id=patient_id,
                report_id=report_id,
            )
        )

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)