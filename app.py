from datetime import date, datetime, timezone

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash

from config import Config
from db import db
from models import Address, Admin, Doctor, Patient, Report  # noqa: F401
from services.gemini import build_environmental_report
from services.risk_profile import RiskProfileError, get_full_risk_profile


ADDRESS_TYPES = {"Home", "Work", "Previous home"}


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    # Generated reports are held in memory (starts empty) until they are
    # stored in the database.
    app.config.setdefault("REPORTS", [])
    db.init_app(app)

    @app.cli.command("init-db")
    def init_db():
        """Create the relational tables; Timescale hypertables are separate."""
        with app.app_context():
            db.create_all()

    # ------------------------------------------------------------------
    # Login / logout
    # ------------------------------------------------------------------
    @app.before_request
    def require_login():
        """Send anyone who isn't signed in to the login page."""
        if request.endpoint in (None, "login", "static"):
            return None
        if session.get("doctor_id") or session.get("admin_id"):
            return None
        return redirect(url_for("login"))

    @app.route("/", methods=["GET", "POST"])
    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None

        if request.method == "POST":
            role = request.form.get("role", "doctor").strip().lower()
            username = request.form.get(
                "username",
                request.form.get("doctor_name", ""),
            ).strip()
            password = request.form.get("password", "")

            if role not in ("doctor", "admin"):
                error = "Please select a valid account type."
            elif not username or not password:
                error = "Please enter your username and password."
            else:
                account_model = Admin if role == "admin" else Doctor
                lowered = username.lower()

                # Match on name (ignoring stray spaces in the stored value),
                # and on email too where the model has one.
                conditions = [
                    db.func.lower(db.func.trim(account_model.name)) == lowered
                ]
                if hasattr(account_model, "email"):
                    conditions.append(
                        db.func.lower(db.func.trim(account_model.email)) == lowered
                    )
                accounts = account_model.query.filter(db.or_(*conditions)).all()

                def password_matches(candidate):
                    stored_hash = (candidate.password_hash or "").strip()
                    if not stored_hash:
                        return False
                    try:
                        return check_password_hash(stored_hash, password)
                    except (ValueError, TypeError):
                        return False

                account = next(
                    (c for c in accounts if password_matches(c)),
                    None,
                )

                if account is None:
                    error = "Name or password is incorrect."
                elif role == "admin":
                    session.clear()
                    session["admin_id"] = account.id
                    return redirect(url_for("admin_dashboard"))
                else:
                    session.clear()
                    session["doctor_id"] = account.id
                    return redirect(url_for("patients"))

        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/admin/dashboard")
    def admin_dashboard():
        admin_id = session.get("admin_id")
        if (
            not isinstance(admin_id, int)
            or db.session.get(Admin, admin_id) is None
        ):
            return redirect(url_for("login"))
        return render_template("admin_dashboard.html")

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def patient_view(record):
        conditions = [
            condition.strip()
            for condition in (record.conditions or "").split(",")
            if condition.strip()
        ]
        addresses = (
            Address.query.filter_by(patient_id=record.id)
            .order_by(Address.id)
            .all()
        )
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
        }

    def find_patient(patient_id):
        record = db.session.get(Patient, patient_id)
        if record is None:
            abort(404)
        return patient_view(record)

    @app.route("/patients", methods=["GET"])
    def patients():
        stored_patients = Patient.query.order_by(Patient.name).all()
        return render_template(
            "patient_list.html",
            patients=[patient_view(p) for p in stored_patients],
            creation_error=None,
        )

    @app.route("/patients/add", methods=["GET", "POST"])
    def add_patient():
        doctors = Doctor.query.order_by(Doctor.id).all()
        error = None

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            nhs_number = "".join(
                request.form.get("nhs_number", "").split()
            ) or None
            dob_text = request.form.get("dob", "").strip()
            ethnicity = request.form.get("ethnicity", "").strip()
            conditions = request.form.get("conditions", "").strip()
            doctor_id_text = request.form.get("doctor_id", "").strip()
            address_type = request.form.get("address_type", "").strip()
            postcode = request.form.get("postcode", "").strip().upper()

            if not all([
                name, dob_text, ethnicity, conditions, doctor_id_text,
                address_type, postcode,
            ]):
                error = "Please complete all required fields."
            elif len(name) > 120:
                error = "The patient's name must be 120 characters or fewer."
            elif nhs_number and (
                not nhs_number.isdigit() or len(nhs_number) != 10
            ):
                error = "Enter a valid 10-digit NHS number."
            elif len(ethnicity) > 80:
                error = "The ethnicity field must be 80 characters or fewer."
            elif len(conditions) > 500:
                error = "Conditions must be 500 characters or fewer."
            elif address_type not in {"Home", "Work"}:
                error = "Choose Home or Work for the address type."
            elif len(postcode) > 10:
                error = "The postcode must be 10 characters or fewer."

            dob = None
            if error is None:
                try:
                    dob = date.fromisoformat(dob_text)
                    if dob > date.today():
                        error = "Date of birth cannot be in the future."
                except ValueError:
                    error = "Please enter a valid date of birth."

            doctor = None
            if error is None:
                try:
                    doctor = db.session.get(Doctor, int(doctor_id_text))
                    if doctor is None:
                        error = "Please select a valid doctor."
                except ValueError:
                    error = "Please select a valid doctor."

            if error is None:
                try:
                    patient = Patient(
                        nhs_number=nhs_number,
                        name=name,
                        dob=dob,
                        ethnicity=ethnicity,
                        conditions=conditions,
                        doctor_id=doctor.id,
                    )
                    db.session.add(patient)
                    # Get the database-generated ID before creating the address.
                    db.session.flush()

                    db.session.add(
                        Address(
                            patient_id=patient.id,
                            address_type=address_type,
                            postcode=postcode,
                        )
                    )
                    # Save patient and address in one transaction.
                    db.session.commit()

                    flash("Patient and address added successfully.", "success")
                    return redirect(
                        url_for("patient_detail", patient_id=patient.id)
                    )
                except IntegrityError:
                    db.session.rollback()
                    error = "The patient could not be saved. Check the details and try again."
                except Exception:
                    db.session.rollback()
                    app.logger.exception("Could not save patient and address")
                    error = "The patient could not be saved. Please try again."

        status = 400 if error else 200
        return render_template(
            "add_patient.html",
            doctors=doctors,
            error=error,
        ), status

    def render_patient_detail(patient, profiles=None, form_error=None):
        reports = [
            report
            for report in app.config["REPORTS"]
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
        dob_text = request.form.get("dob", "").strip()
        conditions = request.form.get("conditions", "").strip()

        if not name or len(name) > 120 or len(conditions) > 500:
            return render_patient_detail(
                patient,
                form_error="Enter a name and keep the fields within their limits.",
            ), 400

        dob = None
        if dob_text:
            try:
                dob = date.fromisoformat(dob_text)
            except ValueError:
                return render_patient_detail(
                    patient,
                    form_error="Enter a valid date of birth.",
                ), 400
            if dob > date.today():
                return render_patient_detail(
                    patient,
                    form_error="Date of birth cannot be in the future.",
                ), 400

        record = db.session.get(Patient, patient_id)
        if record is None:
            abort(404)
        record.name = name
        record.dob = dob
        record.conditions = conditions
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Could not update patient")
            return render_patient_detail(
                patient,
                form_error="The changes could not be saved. Please try again.",
            ), 400
        return redirect(url_for("patient_detail", patient_id=patient_id))

    @app.route("/patients/<int:patient_id>/addresses", methods=["POST"])
    def add_address(patient_id):
        patient = find_patient(patient_id)
        address_type = request.form.get("address_type", "").strip()
        postcode = request.form.get("postcode", "").strip().upper()
        if address_type not in ADDRESS_TYPES or not postcode or len(postcode) > 10:
            return render_patient_detail(
                patient,
                form_error="Choose an address type and enter a valid postcode.",
            ), 400

        db.session.add(
            Address(
                patient_id=patient_id,
                address_type=address_type,
                postcode=postcode,
            )
        )
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Could not add address")
            return render_patient_detail(
                patient,
                form_error="The address could not be saved. Please try again.",
            ), 400
        return redirect(url_for("patient_detail", patient_id=patient_id))

    @app.route(
        "/patients/<int:patient_id>/addresses/<int:address_id>/edit",
        methods=["POST"],
    )
    def edit_address(patient_id, address_id):
        patient = find_patient(patient_id)
        address_type = request.form.get("address_type", "").strip()
        postcode = request.form.get("postcode", "").strip().upper()
        if address_type not in ADDRESS_TYPES or not postcode or len(postcode) > 10:
            return render_patient_detail(
                patient,
                form_error="Choose an address type and enter a valid postcode.",
            ), 400

        record = db.session.get(Address, address_id)
        if record is None or record.patient_id != patient_id:
            abort(404)
        record.address_type = address_type
        record.postcode = postcode
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Could not update address")
            return render_patient_detail(
                patient,
                form_error="The address could not be saved. Please try again.",
            ), 400
        return redirect(url_for("patient_detail", patient_id=patient_id))

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    @app.route("/patients/<int:patient_id>/reports/<int:report_id>")
    def previous_report(patient_id, report_id):
        patient = find_patient(patient_id)
        report = next(
            (
                item
                for item in app.config["REPORTS"]
                if item["id"] == report_id and item["patient_id"] == patient_id
            ),
            None,
        )
        if report is None:
            abort(404)
        return render_template(
            "report.html",
            patient=patient,
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
            except Exception:
                app.logger.exception("Risk profile lookup failed")
                profile = {
                    "postcode": address["postcode"],
                    "errors": {"postcode": "lookup_failed"},
                }
            profiles.append({"address_type": address["type"], "profile": profile})

        try:
            environmental_report = build_environmental_report(
                profiles,
                client=app.config.get("GEMINI_CLIENT"),
            )
        except Exception:
            app.logger.exception("Could not build environmental report")
            flash("The report could not be generated. Please try again.", "error")
            return redirect(url_for("patient_detail", patient_id=patient_id))
        reports = app.config["REPORTS"]
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
    app.run(debug=True, port=5000, threaded=True)