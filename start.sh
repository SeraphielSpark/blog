#!/bin/bash
# Initialize database first
python -c "
from app import app
from models import db

with app.app_context():
    db.create_all()
"

# Start Gunicorn
gunicorn --bind 0.0.0.0:$PORT app:app
