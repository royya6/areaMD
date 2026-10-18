from db import db
from datetime import datetime

class Doctor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255))

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255))

class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nhs_number = db.Column(db.String(20))
    name = db.Column(db.String(120))
    dob = db.Column(db.Date)
    ethnicity = db.Column(db.String(80))
    conditions = db.Column(db.Text)   # comma-separated for MVP
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctor.id"))

class Address(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patient.id"))
    postcode = db.Column(db.String(10))
    address_type = db.Column(db.String(10))   # 'home' or 'work'
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    lsoa_code = db.Column(db.String(12))
    date_from = db.Column(db.Date)
    date_to = db.Column(db.Date, nullable=True)  # null = current

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patient.id"))
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    summary_text = db.Column(db.Text)     # Gemini synthesis output
    news_context = db.Column(db.Text)     # Gemini grounded-search output
    flags_json = db.Column(db.Text)       # raw rule-engine flags, JSON string