#!/bin/bash
# Start Gunicorn
gunicorn --bind 0.0.0.0:$PORT app:app
