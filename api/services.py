"""
Core service layer:
1. geocode_location    — ORS geocoding (free, same key as before)
2. RouteService        — OSRM public demo server, zero auth, no API key needed
                         GET http://router.project-osrm.org/route/v1/driving/{coords}
                         alternatives=true → 1 primary + 1 alternative (2 routes max)
3. FuelOptimizer       — sliding window greedy, starts with initial fill-up at start
                         Ranks all routes by total fuel cost (cheapest first)
"""

import math
import hashlib
import requests
from django.conf import settings
from django.core.cache import cache
from .models import FuelStation


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles between two lat/lon points."""
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def geocode_location(location_str):
    """
    Geocode a free-text US location using OpenRouteService geocoding.
    Returns (lat, lon).
    """
    api_key = settings.ORS_API_KEY
    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        "api_key": api_key,
        "text": location_str,
        "boundary.country": "US",
        "size": 1,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    if not features:
        raise ValueError(f"Could not geocode location: '{location_str}'")
    coords = features[0]["geometry"]["coordinates"]   # [lon, lat]
    return (coords[1], coords[0])                     # (lat, lon)


# ─────────────────────────────────────────────────────────────
# ROUTE SERVICE  — OSRM, no API key, no signup
# ─────────────────────────────────────────────────────────────

class RouteService:
    """
    Uses the OSRM public demo server — completely free, no auth, no card.

    Endpoint:
      GET http://router.project-osrm.org/route/v1/driving/{lon,lat};{lon,lat}

    Params:
      alternatives=true  → up to 1 alternative route (2 routes total)
      geometries=polyline → Google-encoded polyline (precision 5)
      overview=full       → full route geometry, not simplified

    No distance cap. Works for any US route length.
    One GET call returns all routes.
    """

    OSRM_URL = "http://router.project-osrm.org/route/v1/driving/{coordinates}"

    def get_routes(self, start_coords, end_coords):
        """
        Single OSRM API call returning up to 2 driving routes.

        Returns list of route dicts:
          - route_index: int
          - polyline_encoded: str (Google polyline, precision 5)
          - waypoints: list of (lat, lon, cumulative_miles)
          - total_miles: float
        """
        cache_key = "osrm_routes_" + hashlib.md5(
            f"{start_coords}{end_coords}".encode()
        ).hexdigest()
        cached = cache.get(cache_key)
        if cached:
            print("Returning cached OSRM routes.")
            return cached

        # OSRM expects "lon,lat;lon,lat" in the URL path
        coordinates = (
            f"{start_coords[1]},{start_coords[0]};"
            f"{end_coords[1]},{end_coords[0]}"
        )
        url = self.OSRM_URL.format(coordinates=coordinates)

        params = {
            "alternatives": "true",    # request alternative route
            "geometries": "polyline",  # Google-encoded polyline, precision 5
            "overview": "full",        # full geometry, not simplified
            "steps": "false",          # no turn-by-turn, keeps response small
        }

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "Ok":
            raise Exception(f"OSRM error: {data.get('message', data.get('code'))}")

        routes = []
        for idx, route in enumerate(data.get("routes", [])):
            total_meters = route["distance"]
            total_miles = total_meters / 1609.344

            # Decode the polyline to build waypoints with cumulative miles
            encoded_polyline = route["geometry"]
            decoded_coords = self._decode_polyline(encoded_polyline)

            waypoints = []
            cumulative = 0.0
            prev = None
            for lat, lon in decoded_coords:
                if prev:
                    cumulative += haversine_miles(prev[0], prev[1], lat, lon)
                waypoints.append((lat, lon, cumulative))
                prev = (lat, lon)

            routes.append({
                "route_index": idx,
                "polyline_encoded": encoded_polyline,  # pass through as-is
                "waypoints": waypoints,
                "total_miles": total_miles,
            })

        cache.set(cache_key, routes, timeout=getattr(settings, 'ROUTE_CACHE_TTL', 3600))
        return routes

    @staticmethod
    def _decode_polyline(encoded, precision=5):
        """
        Decode a Google-encoded polyline string into list of (lat, lon) tuples.
        OSRM returns polyline with precision=5 by default.
        """
        factor = 10 ** precision
        result = []
        index = 0
        lat = 0
        lon = 0
        length = len(encoded)

        while index < length:
            shift, b, result_lat = 0, 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result_lat |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            lat += (~result_lat >> 1) if (result_lat & 1) else (result_lat >> 1)

            shift, b, result_lon = 0, 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result_lon |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            lon += (~result_lon >> 1) if (result_lon & 1) else (result_lon >> 1)

            result.append((lat / factor, lon / factor))

        return result


# ─────────────────────────────────────────────────────────────
# FUEL OPTIMIZER — sliding window greedy algorithm
# ─────────────────────────────────────────────────────────────

class FuelOptimizer:
    def __init__(self):
        self.range_miles = settings.VEHICLE_RANGE_MILES        # 500
        self.mpg = settings.VEHICLE_MPG                        # 10
        self.tank_gallons = settings.TANK_CAPACITY_GALLONS     # 50
        self.corridor_miles = settings.ROUTE_CORRIDOR_MILES    # 5

    def optimize_all_routes(self, routes, start_coords):
        """
        Run optimization on every route. Return sorted cheapest-first.
        """
        results = []
        for route in routes:
            result = self.find_optimal_stops(route, start_coords)
            results.append(result)

        results.sort(key=lambda r: r["total_fuel_cost"])

        for i, r in enumerate(results):
            r["rank"] = i + 1
            r["is_cheapest"] = (i == 0)

        return results

    def find_optimal_stops(self, route_data, start_coords):
        """
        Optimize fuel stops for a single route.
        Starts with empty tank — fills up at nearest station to start city.
        """
        waypoints = route_data["waypoints"]
        total_miles = route_data["total_miles"]
        route_stations = self._snap_stations_to_route(waypoints)
        stops = self._greedy_select_stops(route_stations, total_miles, start_coords)
        total_gallons = round(sum(s["gallons_purchased"] for s in stops), 2)
        total_cost = sum(s["cost_at_stop"] for s in stops)

        total_detour_miles = round(sum(s.get("distance_from_route_miles", 0) * 2 for s in stops), 2)
        total_detour_gallons = round(total_detour_miles / self.mpg, 3)
        total_distance_traveled = round(total_miles + total_detour_miles, 2)
        total_fuel_burned_gallons = round(total_distance_traveled / self.mpg, 2)

        return {
            "route_index": route_data["route_index"],
            "fuel_stops": stops,
            "total_miles": round(total_miles, 2),
            "total_gallons": round(total_gallons, 2),
            "total_fuel_cost": round(total_cost, 2),
            "total_detour_miles": total_detour_miles,
            "total_detour_gallons_burned": total_detour_gallons,
            "total_distance_traveled": total_distance_traveled,
            "total_fuel_burned_gallons": total_fuel_burned_gallons,
            "polyline_encoded": route_data["polyline_encoded"],
        }

    def _snap_stations_to_route(self, waypoints):
        """
        Filter DB stations to those within corridor_miles of the route.
        1. Bounding box DB query (index scan)
        2. Haversine precision check in Python
        3. Returns sorted by mile_marker
        """
        if not waypoints:
            return []

        lats = [wp[0] for wp in waypoints]
        lons = [wp[1] for wp in waypoints]
        pad = self.corridor_miles / 69.0

        candidates = FuelStation.objects.filter(
            latitude__gte=min(lats) - pad, latitude__lte=max(lats) + pad,
            longitude__gte=min(lons) - pad, longitude__lte=max(lons) + pad,
            latitude__isnull=False, longitude__isnull=False,
        ).values('id', 'name', 'city', 'state', 'address', 'retail_price', 'latitude', 'longitude')

        sample_step = max(1, len(waypoints) // 500)
        sampled_wps = waypoints[::sample_step]

        route_stations = []
        for station in candidates:
            slat, slon = station['latitude'], station['longitude']
            min_dist = float('inf')
            closest_mile = 0.0

            for wp_lat, wp_lon, wp_mile in sampled_wps:
                if abs(wp_lat - slat) > 0.15 or abs(wp_lon - slon) > 0.15:
                    continue
                d = haversine_miles(slat, slon, wp_lat, wp_lon)
                if d < min_dist:
                    min_dist = d
                    closest_mile = wp_mile

            if min_dist <= self.corridor_miles:
                route_stations.append({
                    "name": station['name'],
                    "city": station['city'],
                    "state": station['state'],
                    "address": station['address'],
                    "retail_price": round(station['retail_price'], 3),
                    "latitude": slat,
                    "longitude": slon,
                    "mile_marker": round(closest_mile, 1),
                    "distance_from_route_miles": round(min_dist, 2),
                })

        route_stations.sort(key=lambda x: x['mile_marker'])
        return route_stations

    def _find_initial_station(self, start_coords):
        """
        Find the cheapest fuel station near the start city by querying the DB
        directly around start_coords — NOT limited to the route corridor.
        Searches within a 10-mile radius, picks cheapest (ties broken by proximity).
        """
        start_lat, start_lon = start_coords
        radius_miles = 10
        pad = radius_miles / 69.0

        candidates = FuelStation.objects.filter(
            latitude__gte=start_lat - pad, latitude__lte=start_lat + pad,
            longitude__gte=start_lon - pad, longitude__lte=start_lon + pad,
            latitude__isnull=False, longitude__isnull=False,
        ).values('name', 'city', 'state', 'address', 'retail_price', 'latitude', 'longitude')

        nearby = []
        for s in candidates:
            dist = haversine_miles(start_lat, start_lon, s['latitude'], s['longitude'])
            if dist <= radius_miles:
                nearby.append({**s, 'distance_from_start_miles': round(dist, 2)})

        if not nearby:
            return None

        # Cheapest in city; break ties by proximity
        best = min(nearby, key=lambda s: (s['retail_price'], s['distance_from_start_miles']))
        return {
            'name': best['name'],
            'city': best['city'],
            'state': best['state'],
            'address': best['address'],
            'retail_price': round(best['retail_price'], 3),
            'latitude': best['latitude'],
            'longitude': best['longitude'],
            'mile_marker': 0.0,
            'distance_from_route_miles': best['distance_from_start_miles'],
        }

    def _greedy_select_stops(self, route_stations, total_miles, start_coords):
        """
        Sliding window greedy algorithm.

        Step 0: Fill full tank at the nearest station to the start city.
        Then: greedily pick the cheapest station within the current fuel window,
              fill to full tank, repeat until destination is in range.
        """
        if not route_stations:
            return []

        stops = []

        # ── Initial fill-up at start city ────────────────────────────
        initial = self._find_initial_station(start_coords)
        if not initial:
            return []

        current_mile = initial['mile_marker']  # 0.0

        # Remove initial station from route_stations to avoid duplicate stop
        route_stations = [
            s for s in route_stations
            if not (
                abs(s['latitude'] - initial['latitude']) < 0.001 and
                abs(s['longitude'] - initial['longitude']) < 0.001
            )
        ]

        # Check the first en-route station ahead.
        # If it's cheaper → fill just enough to reach it.
        # If it's more expensive (or none) → fill full tank.
        first_ahead = next(
            (s for s in route_stations if s['mile_marker'] > 0),
            None
        )

        if first_ahead and first_ahead['retail_price'] < initial['retail_price']:
            # Cheaper ahead — fill just enough to reach it (include its detour)
            miles_needed = first_ahead['mile_marker'] + (first_ahead.get('distance_from_route_miles', 0.0) * 2)
            gallons_to_fill = round(min(self.tank_gallons, miles_needed / self.mpg), 2)
            fill_strategy = "partial_fillup"
        else:
            # Start is cheapest (or no stations ahead) — fill full tank
            gallons_to_fill = self.tank_gallons
            fill_strategy = "full_fillup"

        stops.append({
            **{k: initial[k] for k in [
                'name', 'city', 'state', 'address',
                'retail_price', 'latitude', 'longitude',
                'mile_marker', 'distance_from_route_miles'
            ]},
            "gallons_purchased": gallons_to_fill,
            "cost_at_stop": round(gallons_to_fill * initial['retail_price'], 2),
            "stop_type": "initial_fillup",
            "fill_strategy": fill_strategy,
        })

        remaining_fuel_miles = gallons_to_fill * self.mpg

        # ── Greedy sliding window ─────────────────────────────────────
        while current_mile + remaining_fuel_miles < total_miles:
            window_end = current_mile + remaining_fuel_miles
            window = [
                s for s in route_stations
                if current_mile < s['mile_marker'] <= window_end
            ]

            if not window:
                beyond = [s for s in route_stations if s['mile_marker'] > current_mile]
                if not beyond:
                    break
                window = [beyond[0]]

            best = min(window, key=lambda s: s['retail_price'])

            # Actual miles driven to reach this station:
            # route miles along the path + detour to station + detour back to route
            detour = best.get('distance_from_route_miles', 0.0)
            actual_miles_driven = (best['mile_marker'] - current_mile) + (detour * 2)
            fuel_used = actual_miles_driven / self.mpg
            gallons_remaining = (remaining_fuel_miles / self.mpg) - fuel_used

            if gallons_remaining < 0:
                # Can't reach this station — ran out of fuel. Skip it.
                current_mile = best['mile_marker']
                remaining_fuel_miles = 0.0
                break

            # Gallons needed to finish: remaining route miles + detours for future stops
            # We approximate future detours as 0 here (conservative — driver may skip detours)
            miles_to_finish = total_miles - best['mile_marker']
            gallons_needed_to_finish = max(0.0, (miles_to_finish / self.mpg) - gallons_remaining)

            # If we already have enough fuel to finish, skip this stop entirely
            if gallons_needed_to_finish <= 0:
                current_mile = best['mile_marker']
                remaining_fuel_miles = gallons_remaining * self.mpg
                continue

            # Look ahead: is there a cheaper station within reachable range from here?
            # Use remaining range AFTER filling enough to get to next stop
            next_ahead = [
                s for s in route_stations
                if best['mile_marker'] < s['mile_marker'] <= best['mile_marker'] + self.range_miles
            ]

            if next_ahead:
                next_cheapest = min(next_ahead, key=lambda s: s['retail_price'])
                if next_cheapest['retail_price'] < best['retail_price']:
                    # Cheaper station ahead — fill just enough to reach it
                    # Account for detour to next station too
                    next_detour = next_cheapest.get('distance_from_route_miles', 0.0)
                    miles_to_next = (next_cheapest['mile_marker'] - best['mile_marker']) + (next_detour * 2)
                    gallons_to_fill = round(
                        max(0.0, (miles_to_next / self.mpg) - gallons_remaining), 2
                    )
                    fill_strategy = "partial_fillup"
                else:
                    # This is cheapest in range — fill as much as needed but no more than tank
                    gallons_to_fill = round(
                        min(self.tank_gallons - gallons_remaining, gallons_needed_to_finish), 2
                    )
                    fill_strategy = "full_fillup" if gallons_to_fill >= self.tank_gallons - gallons_remaining - 0.01 else "final_fillup"
            else:
                # No more stations — fill exactly enough to reach destination
                gallons_to_fill = round(gallons_needed_to_finish, 2)
                fill_strategy = "final_fillup"

            # Hard safety cap: never exceed tank capacity, never negative
            max_fillable = self.tank_gallons - gallons_remaining
            gallons_to_fill = round(max(0.0, min(gallons_to_fill, max_fillable)), 2)

            # Skip stop if nothing to buy
            if gallons_to_fill <= 0:
                current_mile = best['mile_marker']
                remaining_fuel_miles = gallons_remaining * self.mpg
                continue

            new_remaining_fuel_miles = (gallons_remaining + gallons_to_fill) * self.mpg

            stops.append({
                **{k: best[k] for k in [
                    'name', 'city', 'state', 'address',
                    'retail_price', 'latitude', 'longitude',
                    'mile_marker', 'distance_from_route_miles'
                ]},
                "gallons_purchased": gallons_to_fill,
                "cost_at_stop": round(gallons_to_fill * best['retail_price'], 2),
                "stop_type": "en_route",
                "fill_strategy": fill_strategy,
            })

            current_mile = best['mile_marker']
            remaining_fuel_miles = new_remaining_fuel_miles

        return stops