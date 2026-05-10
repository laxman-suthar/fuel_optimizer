import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'secret-key')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')

INSTALLED_APPS = [
    'django.contrib.auth',          # <-- ADD THIS
    'django.contrib.contenttypes',
    'django.contrib.sessions',      # <-- ADD THIS (Required for auth sessions)
    'django.contrib.staticfiles',
    'rest_framework',
    'api',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'fuel_optimizer.urls'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'fuel_optimizer'),
        'USER': os.environ.get('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
        'HOST': os.environ.get('POSTGRES_HOST', 'db'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STATIC_URL = '/static/'

# OpenRouteService free API - get your own key at openrouteservice.org
ORS_API_KEY = os.environ.get('ORS_API_KEY', '5b3ce3597851110001cf6248a2e91e29e24541e6bb8a38d08a09e2c0')

 

# Vehicle specs
VEHICLE_RANGE_MILES = 500
VEHICLE_MPG = 10
TANK_CAPACITY_GALLONS = VEHICLE_RANGE_MILES / VEHICLE_MPG  # 50 gallons

# Station must be within this many miles of route to be considered
ROUTE_CORRIDOR_MILES = 5

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ]
}

# Cache timeout for route responses (seconds)
ROUTE_CACHE_TTL = int(os.environ.get('ROUTE_CACHE_TTL', 3600))

REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379/1')

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'TIMEOUT': ROUTE_CACHE_TTL,
    }
}
