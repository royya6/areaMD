from app import create_app
from db import db
from models import Doctor
from werkzeug.security import generate_password_hash

app = create_app()
with app.app_context():
    d = Doctor.query.filter_by(name="Dr Amy Smith").first()
    print("found:", d is not None)
    if d:
        d.password_hash = generate_password_hash("demo1234", method="pbkdf2:sha256")
        db.session.commit()
        print("updated, hash starts:", d.password_hash[:20])


    print("database:", db.engine.url.render_as_string(hide_password=True))
    doctors = Doctor.query.all()
    print("count:", len(doctors))
    for d in doctors:
        print(d.id, repr(d.name))