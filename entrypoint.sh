#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
until python -c "
import psycopg2, os, sys
try:
    psycopg2.connect(
        dbname=os.environ.get('POSTGRES_DB','fuel_optimizer'),
        user=os.environ.get('POSTGRES_USER','postgres'),
        password=os.environ.get('POSTGRES_PASSWORD','postgres'),
        host=os.environ.get('POSTGRES_HOST','db'),
        port=os.environ.get('POSTGRES_PORT','5432'),
    )
    print('PostgreSQL ready')
except Exception as e:
    print(f'Not ready: {e}')
    sys.exit(1)
"; do
  echo "  PostgreSQL not ready yet, retrying in 2s..."
  sleep 2
done

echo "Running migrations..."
python manage.py migrate --noinput

echo "Loading fuel stations..."
python manage.py load_fuel_stations_fast

echo "Starting Gunicorn..."
exec gunicorn fuel_optimizer.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
