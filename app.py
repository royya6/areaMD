from flask import Flask, render_template
from config import Config
from db import db

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    from models import Doctor, Patient, Address, Report  # noqa

    with app.app_context():
        db.create_all()  # relational tables only — hypertable created separately, see step 5

    @app.route("/")
    def index():
        return render_template("login.html")

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)