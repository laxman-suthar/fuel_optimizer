#!/usr/bin/env python3
"""
One-time geocoding script with RESUME support.
If interrupted, re-run and it picks up from where it stopped.

Usage: python geocode_cities.py
"""
import csv, json, time, requests, os, signal, sys

STATE_COORDS = {
    "AL": (32.806671, -86.791130), "AZ": (33.729759, -111.431221),
    "AR": (34.969704, -92.373123), "CA": (36.116203, -119.681564),
    "CO": (39.059811, -105.311104), "CT": (41.597782, -72.755371),
    "DE": (39.318523, -75.507141), "FL": (27.766279, -81.686783),
    "GA": (33.040619, -83.643074), "ID": (44.240459, -114.478828),
    "IL": (40.349457, -88.986137), "IN": (39.849426, -86.258278),
    "IA": (42.011539, -93.210526), "KS": (38.526600, -96.726486),
    "KY": (37.668140, -84.670067), "LA": (31.169960, -91.867805),
    "ME": (44.693947, -69.381927), "MD": (39.063946, -76.802101),
    "MA": (42.230171, -71.530106), "MI": (43.326618, -84.536095),
    "MN": (45.694454, -93.900192), "MS": (32.741646, -89.678696),
    "MO": (38.456085, -92.288368), "MT": (46.921925, -110.454353),
    "NE": (41.125370, -98.268082), "NV": (38.313515, -117.055374),
    "NH": (43.452492, -71.563896), "NJ": (40.298904, -74.521011),
    "NM": (34.840515, -106.248482), "NY": (42.165726, -74.948051),
    "NC": (35.630066, -79.806419), "ND": (47.528912, -99.784012),
    "OH": (40.388783, -82.764915), "OK": (35.565342, -96.928917),
    "OR": (44.572021, -122.070938), "PA": (40.590752, -77.209755),
    "SC": (33.856892, -80.945007), "SD": (44.299782, -99.438828),
    "TN": (35.747845, -86.692345), "TX": (31.054487, -97.563461),
    "UT": (40.150032, -111.862434), "VA": (37.769337, -78.169968),
    "WA": (47.400902, -121.490494), "WV": (38.491226, -80.954453),
    "WI": (44.268543, -89.616508), "WY": (42.755966, -107.302490),
}

OUTPUT_FILE = "api/city_coords.json"
CHECKPOINT_FILE = "api/city_coords_checkpoint.json"  # saves every 50 cities

# ── Load existing progress (resume support) ──────────────────
result = {}
if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE) as f:
        result = json.load(f)
    print(f"Resuming from checkpoint — {len(result)} cities already done.")
elif os.path.exists(OUTPUT_FILE):
    with open(OUTPUT_FILE) as f:
        result = json.load(f)
    print(f"Resuming from output file — {len(result)} cities already done.")

# ── Load all unique cities ────────────────────────────────────
cities = []
seen = set()
with open("api/fuel_prices.csv") as f:
    for row in csv.DictReader(f):
        state = row["State"].strip().upper()
        city = row["City"].strip()
        key = f"{city.upper()}|{state}"
        if state in STATE_COORDS and key not in seen:
            seen.add(key)
            cities.append((city, state, key))

total = len(cities)

# Filter out already-done cities
remaining = [(city, state, key) for city, state, key in cities if key not in result]
print(f"Total: {total} | Already done: {total - len(remaining)} | Remaining: {len(remaining)}")

if not remaining:
    print("All cities already geocoded!")
    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f)
    print(f"Saved to {OUTPUT_FILE}")
    sys.exit(0)

# ── Graceful shutdown on Ctrl+C ───────────────────────────────
def save_and_exit(sig, frame):
    print(f"\nInterrupted! Saving checkpoint ({len(result)} cities done)...")
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(result, f)
    print(f"Checkpoint saved to {CHECKPOINT_FILE}. Re-run to resume.")
    sys.exit(0)

signal.signal(signal.SIGINT, save_and_exit)
signal.signal(signal.SIGTERM, save_and_exit)

# ── Geocode remaining cities ──────────────────────────────────
done_this_run = 0
for i, (city, state, key) in enumerate(remaining):
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"city": city, "state": state, "country": "US",
                    "format": "json", "limit": 1},
            headers={"User-Agent": "FuelOptimizerSetup/1.0"},
            timeout=8,
        )
        data = resp.json()
        if data:
            result[key] = [float(data[0]["lat"]), float(data[0]["lon"])]
        else:
            result[key] = list(STATE_COORDS[state])
    except Exception as e:
        result[key] = list(STATE_COORDS.get(state, [39.5, -98.35]))

    done_this_run += 1
    overall_done = (total - len(remaining)) + done_this_run

    # Progress every 10 cities
    if done_this_run % 10 == 0:
        print(f"  {overall_done}/{total} done... ({city}, {state})")

    # Save checkpoint every 50 cities
    if done_this_run % 50 == 0:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(result, f)

    time.sleep(1.1)  # Nominatim rate limit: 1 req/sec

# ── All done — write final output ────────────────────────────
with open(OUTPUT_FILE, "w") as f:
    json.dump(result, f)

# Clean up checkpoint file
if os.path.exists(CHECKPOINT_FILE):
    os.remove(CHECKPOINT_FILE)

print(f"\nDone! {len(result)} cities saved to {OUTPUT_FILE}")