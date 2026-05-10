"""
Management command: python manage.py load_fuel_stations

Reads the CSV, geocodes each unique city/state using Nominatim (free OSM API),
and bulk-saves all stations to the DB.

Geocoding is cached by (city, state) to minimize API calls.
~1,200 unique city/state pairs in the dataset → ~1200 Nominatim calls.
Run once at setup time.
"""

import csv
import time
import requests
from django.core.management.base import BaseCommand
from api.models import FuelStation


STATE_COORDS = {
    'AL': (32.806671, -86.791130), 'AK': (61.370716, -152.404419),
    'AZ': (33.729759, -111.431221), 'AR': (34.969704, -92.373123),
    'CA': (36.116203, -119.681564), 'CO': (39.059811, -105.311104),
    'CT': (41.597782, -72.755371), 'DE': (39.318523, -75.507141),
    'FL': (27.766279, -81.686783), 'GA': (33.040619, -83.643074),
    'HI': (21.094318, -157.498337), 'ID': (44.240459, -114.478828),
    'IL': (40.349457, -88.986137), 'IN': (39.849426, -86.258278),
    'IA': (42.011539, -93.210526), 'KS': (38.526600, -96.726486),
    'KY': (37.668140, -84.670067), 'LA': (31.169960, -91.867805),
    'ME': (44.693947, -69.381927), 'MD': (39.063946, -76.802101),
    'MA': (42.230171, -71.530106), 'MI': (43.326618, -84.536095),
    'MN': (45.694454, -93.900192), 'MS': (32.741646, -89.678696),
    'MO': (38.456085, -92.288368), 'MT': (46.921925, -110.454353),
    'NE': (41.125370, -98.268082), 'NV': (38.313515, -117.055374),
    'NH': (43.452492, -71.563896), 'NJ': (40.298904, -74.521011),
    'NM': (34.840515, -106.248482), 'NY': (42.165726, -74.948051),
    'NC': (35.630066, -79.806419), 'ND': (47.528912, -99.784012),
    'OH': (40.388783, -82.764915), 'OK': (35.565342, -96.928917),
    'OR': (44.572021, -122.070938), 'PA': (40.590752, -77.209755),
    'RI': (41.680893, -71.511780), 'SC': (33.856892, -80.945007),
    'SD': (44.299782, -99.438828), 'TN': (35.747845, -86.692345),
    'TX': (31.054487, -97.563461), 'UT': (40.150032, -111.862434),
    'VT': (44.045876, -72.710686), 'VA': (37.769337, -78.169968),
    'WA': (47.400902, -121.490494), 'WV': (38.491226, -80.954453),
    'WI': (44.268543, -89.616508), 'WY': (42.755966, -107.302490),
    'DC': (38.897438, -77.026817),
}


class Command(BaseCommand):
    help = 'Load fuel stations from CSV with geocoding'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv',
            default='api/fuel_prices.csv',
            help='Path to fuel prices CSV file'
        )

    def handle(self, *args, **options):
        csv_path = options['csv']
        self.stdout.write(f"Loading fuel stations from {csv_path}...")

        FuelStation.objects.all().delete()

        geocode_cache = {}

        def geocode_city_state(city, state):
            key = (city.lower(), state.upper())
            if key in geocode_cache:
                return geocode_cache[key]
            try:
                url = "https://nominatim.openstreetmap.org/search"
                params = {
                    "city": city, "state": state,
                    "country": "US", "format": "json", "limit": 1,
                }
                headers = {"User-Agent": "FuelOptimizerApp/1.0"}
                resp = requests.get(url, params=params, headers=headers, timeout=8)
                results = resp.json()
                if results:
                    coords = (float(results[0]['lat']), float(results[0]['lon']))
                    geocode_cache[key] = coords
                    time.sleep(1.1)
                    return coords
            except Exception:
                pass
            coords = STATE_COORDS.get(state.upper(), (39.5, -98.35))
            geocode_cache[key] = coords
            return coords

        stations_data = []
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    price = float(row['Retail Price'])
                    stations_data.append({
                        'opis_id': int(row['OPIS Truckstop ID']),
                        'name': row['Truckstop Name'].strip(),
                        'address': row['Address'].strip(),
                        'city': row['City'].strip(),
                        'state': row['State'].strip(),
                        'retail_price': price,
                    })
                except (ValueError, KeyError):
                    continue

        total = len(stations_data)
        self.stdout.write(f"Found {total} station records.")

        unique_cities = set((s['city'], s['state']) for s in stations_data)
        self.stdout.write(f"Geocoding {len(unique_cities)} unique city/state pairs...")

        for i, (city, state) in enumerate(unique_cities):
            geocode_city_state(city, state)
            if (i + 1) % 50 == 0:
                self.stdout.write(f"  Geocoded {i+1}/{len(unique_cities)} cities...")

        self.stdout.write("Saving stations to DB...")
        batch = []
        for s in stations_data:
            lat, lon = geocode_cache.get(
                (s['city'].lower(), s['state'].upper()),
                STATE_COORDS.get(s['state'].upper(), (39.5, -98.35))
            )
            batch.append(FuelStation(
                opis_id=s['opis_id'],
                name=s['name'],
                address=s['address'],
                city=s['city'],
                state=s['state'],
                retail_price=s['retail_price'],
                latitude=lat,
                longitude=lon,
            ))
            if len(batch) >= 500:
                FuelStation.objects.bulk_create(batch)
                batch = []

        if batch:
            FuelStation.objects.bulk_create(batch)

        count = FuelStation.objects.count()
        self.stdout.write(self.style.SUCCESS(f"✓ Loaded {count} fuel stations successfully!"))
