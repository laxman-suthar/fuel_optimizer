

# Smart Refuel API

# Fuel Route Optimizer API

A Django REST API that calculates the most cost-effective fuel stops for long-distance US road trips using a greedy sliding-window optimization algorithm.

This project returns the cheapest fueling strategy including:

- Initial departure fuel fill-up
- En-route cheapest fuel stops
- Partial / full fill-up strategy
- Total trip fuel cost
- Detour miles and fuel burn
- Route optimization summary

---

# API Endpoint

## POST `/api/trip/`

### Request

```json
{
  "start": "Chicago, IL",
  "finish": "Dallas, TX"
}
```

---

# Example Response

```json
{
  "trip": {
    "start": "Chicago, IL",
    "finish": "Dallas, TX",
    "start_coords": {
      "lat": 41.87897,
      "lng": -87.66063
    },
    "finish_coords": {
      "lat": 32.736212,
      "lng": -96.784359
    }
  },

  "route": {
    "start_fuel": {
      "station_name": "Gas N Wash",
      "address": "I-55, EXIT 285",
      "city": "Chicago",
      "state": "IL",
      "price_per_gallon_usd": 3.399,
      "gallons_purchased": 50.0,
      "cost_usd": 169.95,
      "mile_marker": 0.0
    },

    "fuel_stops": [
      {
        "name": "Gas N Wash",
        "city": "Chicago",
        "state": "IL",
        "retail_price": 3.399,
        "gallons_purchased": 50.0,
        "cost_at_stop": 169.95,
        "stop_type": "initial_fillup",
        "fill_strategy": "full_fillup"
      },
      {
        "name": "QUIKTRIP #605",
        "city": "Saint Louis",
        "state": "MO",
        "retail_price": 2.899,
        "gallons_purchased": 29.51,
        "cost_at_stop": 85.55,
        "stop_type": "en_route",
        "fill_strategy": "full_fillup"
      }
    ],

    "summary": {
      "total_stops": 3,
      "en_route_stops": 2,
      "distance_start_to_finish_miles": 926.65,
      "total_detour_miles": 10.56,
      "total_distance_traveled_miles": 937.21,
      "total_gallons_purchased": 93.07,
      "total_fuel_cost_usd": 294.81,
      "avg_price_per_gallon": 3.168
    }
  }
}
```

---

# Fuel Optimization Logic

## Step 1 — Initial Fill-Up

The system finds the cheapest fuel station near the start city.

If cheaper fuel exists ahead:
- partial fill-up

Else:
- full tank fill-up

This reduces unnecessary expensive fuel purchases.

---

## Step 2 — Sliding Window Greedy Optimization

Vehicle assumptions:

- MPG = 10
- Tank Capacity = 50 gallons
- Max Range = 500 miles

Algorithm:

```text
Current Window:
[current_position → current_position + fuel_range]

1. Find reachable stations
2. Pick cheapest station
3. If cheaper fuel exists ahead:
      buy minimum required fuel
4. Else:
      fill tank economically
5. Repeat until destination is reachable
```

---

# Stack

- Django 5.2.14
- Django REST Framework
- PostgreSQL 16
- Redis 7
- Docker + Docker Compose
- Gunicorn
- OpenRouteService (Geocoding)
- OSRM (Routing)

---

# Run Project

```bash
docker compose up --build
```

---

# Result

The API returns:

- Cheapest fuel plan
- Initial start fuel
- En-route fuel stops
- Full / partial fill strategy
- Total fuel cost
- Distance + detour summary
- Optimized road trip response
