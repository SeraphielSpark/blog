#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

# Initialize database
python -c "
from app import app
from models import db, User, Post, Comment

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', online=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
"
