<<<<<<< HEAD
from flask import Flask, render_template, request, session, abort, redirect, url_for
from flask_migrate import Migrate
from config import Config
from db import db
from werkzeug.security import check_password_hash
from copy import deepcopy
from datetime import date
from sqlalchemy.exc import IntegrityError
=======
from copy import deepcopy
from datetime import date, datetime, timezone

from flask import Flask, abort, redirect, render_template, request, url_for

from config import Config
from db import db
from services.gemini import build_environmental_report
>>>>>>> 80879e743150af7eda17b3138d54a6666bdc1bf0
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
    migrate = Migrate(app, db)

    from models import Doctor, Patient, Address, Report  # noqa

    @app.cli.command("init-db")
    def init_db():
        """Create the relational tables; Timescale hypertables are separate."""
        with app.app_context():
            db.create_all()

    @app.route("/", methods=["GET", "POST"])
    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            doctor_name = request.form.get("doctor_name", "").strip()
            password = request.form.get("password", "")
            doctors = Doctor.query.filter(
                db.func.lower(Doctor.name) == doctor_name.lower()
            ).all()

            def password_matches(candidate):
                stored_hash = (candidate.password_hash or "").strip()
                if not stored_hash:
                    return False
                try:
                    return check_password_hash(stored_hash, password)
                except ValueError:
                    return False

            doctor = next(
                (
                    candidate
                    for candidate in doctors
                    if password_matches(candidate)
                ),
                None,
            )
            if doctor is None:
                error = "Doctor name or password is incorrect."
            else:
                session["doctor_id"] = doctor.id
                return redirect(url_for("patients"))

        return render_template("login.html", error=error)

    def patient_view(record):
        conditions = [
            condition.strip()
            for condition in (record.conditions or "").split(",")
            if condition.strip()
        ]
        addresses = Address.query.filter_by(patient_id=record.id).order_by(
            Address.id
        ).all()
        return {
            "id": record.id,
            "name": record.name,
            "dob": record.dob.isoformat() if record.dob else "",
            "ethnicity": record.ethnicity,
            "nhs_number": record.nhs_number,
            "conditions": conditions,
            "addresses": [
                {
                    "id": address.id,
                    "type": address.address_type or "Home",
                    "postcode": address.postcode or "",
                }
                for address in addresses
            ],
            "database_record": True,
        }

    def all_patient_views():
        stored_patients = Patient.query.order_by(Patient.name).all()
        return app.config["MOCK_PATIENTS"] + [
            patient_view(patient) for patient in stored_patients
        ]

    def render_patient_list(error=None):
        return render_template(
            "patient_list.html",
            patients=all_patient_views(),
            creation_error=error,
        )

    @app.route("/patients", methods=["GET", "POST"])
    def patients():
        if request.method == "POST":
            doctor_id = session.get("doctor_id")
            doctor = (
                db.session.get(Doctor, doctor_id)
                if isinstance(doctor_id, int) and not isinstance(doctor_id, bool)
                else None
            )
            if doctor is None:
                return redirect(url_for("login"))

            name = request.form.get("name", "").strip()
            dob_value = request.form.get("dob", "").strip()
            ethnicity = request.form.get("ethnicity", "").strip()
            conditions = request.form.get("conditions", "").strip()
            nhs_number = "".join(request.form.get("nhs_number", "").split())

            if not name or not dob_value or not ethnicity or not conditions:
                return render_patient_list(
                    "Complete all required patient fields."
                ), 400
            if len(name) > 120 or len(ethnicity) > 80 or len(conditions) > 500:
                return render_patient_list(
                    "Keep name, ethnicity, and conditions within their field limits."
                ), 400
            try:
                dob = date.fromisoformat(dob_value)
            except ValueError:
                return render_patient_list("Enter a valid date of birth."), 400
            if dob.isoformat() != dob_value or dob > date.today():
                return render_patient_list("Enter a valid date of birth."), 400
            if nhs_number and (not nhs_number.isdigit() or len(nhs_number) != 10):
                return render_patient_list(
                    "Enter a 10-digit NHS number or leave it blank."
                ), 400

            mock_max_id = max(
                (patient["id"] for patient in app.config["MOCK_PATIENTS"]),
                default=0,
            )
            stored_max_id = db.session.query(db.func.max(Patient.id)).scalar() or 0
            patient = Patient(
                id=max(mock_max_id, stored_max_id) + 1,
                name=name,
                dob=dob,
                ethnicity=ethnicity,
                conditions=conditions,
                nhs_number=nhs_number or None,
                doctor_id=doctor.id,
            )
            db.session.add(patient)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                return render_patient_list(
                    "The patient could not be saved. Check the details and try again."
                ), 400
            return redirect(url_for("patients"))

        return render_patient_list()

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
            record = db.session.get(Patient, patient_id)
            if record is None:
                abort(404)
            return patient_view(record)
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