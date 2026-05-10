# Fuel Route Optimizer API

A Django REST API that plans the most **cost-effective fuel stops** for a US road trip.

## How It Works

Given a start and finish location in the USA, the API:
1. Geocodes both locations (OpenRouteService)
2. Fetches the driving route — **exactly 1 API call** to OpenRouteService
3. Runs a **greedy sliding window algorithm** to find cheapest fuel stops
4. Returns the route polyline, all fuel stops with prices, and total trip fuel cost

### Algorithm

```
Window = [current_position → current_position + 500 miles (full tank)]

At each step:
  → Find all stations reachable in the window
  → Pick the CHEAPEST one
  → Fill tank, slide window forward
  → Repeat until destination is in range
```

---

## Stack

| Layer | Technology |
|---|---|
| Framework | Django 5.1 + Django REST Framework |
| Database | PostgreSQL 16 |
| Cache | Redis 7 (via django-redis) |
| Server | Gunicorn |
| Routing API | OpenRouteService (free tier) |
| Containerization | Docker + Docker Compose |

---

## Quick Start (Docker)

### 1. Clone & configure

```bash
git clone <repo>
cd fuel_optimizer
cp .env.example .env
```

Edit `.env` and set your `ORS_API_KEY` (free at [openrouteservice.org](https://openrouteservice.org/dev/#/signup)).

### 2. Run

```bash
docker compose up --build
```

That's it. Docker will:
- Start PostgreSQL + Redis
- Run migrations
- Load all 8,150 fuel stations
- Start Gunicorn on port 8000

### 3. Hit the API

```bash
curl -X POST http://localhost:8000/api/trip/ \
  -H "Content-Type: application/json" \
  -d '{"start": "New York, NY", "finish": "Los Angeles, CA"}'
```

---

## API

### `POST /api/trip/`

**Request:**
```json
{
    "start": "New York, NY",
    "finish": "Los Angeles, CA"
}
```

**Response:**
```json
{
    "trip": {
        "start": "New York, NY",
        "finish": "Los Angeles, CA",
        "start_coords": {"lat": 40.7128, "lng": -74.006},
        "finish_coords": {"lat": 34.0522, "lng": -118.2437}
    },
    "route": {
        "total_miles": 2789.4,
        "total_gallons_used": 278.9,
        "polyline_encoded": "encoded_string_for_google_maps..."
    },
    "fuel_stops": [
        {
            "name": "LOVES TRAVEL STOP #766",
            "city": "Atkinson",
            "state": "IL",
            "address": "I-80, EXIT 27",
            "retail_price": 3.389,
            "latitude": 40.349,
            "longitude": -88.986,
            "mile_marker": 347.2,
            "distance_from_route_miles": 1.4,
            "gallons_purchased": 50.0,
            "cost_at_stop": 169.45
        }
    ],
    "summary": {
        "total_stops": 6,
        "total_fuel_cost_usd": 987.23,
        "avg_price_per_gallon": 3.539
    },
    "meta": {
        "response_time_seconds": 1.23,
        "vehicle_range_miles": 500,
        "vehicle_mpg": 10
    }
}
```

---

## External API Calls Per Request

| Step | Calls |
|---|---|
| Geocode start | 1 (ORS) |
| Geocode finish | 1 (ORS) |
| Get route | 1 (ORS) |
| Fuel optimization | 0 (local DB + Redis) |
| **Total** | **3 max** |

Routes are cached in Redis for 1 hour — repeat requests = **0 external calls**.

---

## Project Structure

```
fuel_optimizer/
├── api/
│   ├── management/commands/
│   │   ├── load_fuel_stations.py        # Nominatim geocoder (accurate, slow)
│   │   └── load_fuel_stations_fast.py   # Fast loader with fallback
│   ├── fuel_prices.csv                  # 8,150 US truck stops
│   ├── models.py                        # FuelStation model
│   ├── services.py                      # RouteService + FuelOptimizer
│   ├── views.py                         # TripPlanView
│   └── urls.py
├── fuel_optimizer/
│   ├── settings.py                      # All config via env vars
│   └── urls.py
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh                        # Waits for DB, migrates, starts server
├── .env.example
├── requirements.txt
└── README.md
```

---

## Running Without Docker

```bash
pip install -r requirements.txt

# Set env vars or update settings.py directly
export POSTGRES_HOST=localhost
export REDIS_URL=redis://localhost:6379/1
export ORS_API_KEY=your-key

python manage.py migrate
python manage.py load_fuel_stations_fast
python manage.py runserver
```
