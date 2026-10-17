from flask import Flask, render_template, request, session
from flask_migrate import Migrate
from config import Config
from db import db
from werkzeug.security import check_password_hash

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    migrate = Migrate(app, db)

    from models import Doctor, Patient, Address, Report  # noqa

    with app.app_context():
        db.create_all()  # relational tables only — hypertable created separately, see step 5

    @app.route("/", methods=["GET", "POST"])
    def index():
        error = None
        if request.method == "POST":
            doctor_name = request.form.get("doctor_name", "").strip()
            password = request.form.get("password", "")
            doctors = Doctor.query.filter(
                db.func.lower(Doctor.name) == doctor_name.lower()
            ).all()
            doctor = next(
                (
                    candidate
                    for candidate in doctors
                    if candidate.password_hash
                    and check_password_hash(candidate.password_hash, password)
                ),
                None,
            )
            if doctor is None:
                error = "Doctor name or password is incorrect."
            else:
                session["doctor_id"] = doctor.id

        return render_template("login.html", error=error)

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)