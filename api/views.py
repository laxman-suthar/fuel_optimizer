import time
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .services import RouteService, FuelOptimizer, geocode_location


class TripPlanView(APIView):
    """
    POST /api/trip/
    Body: { "start": "New York, NY", "finish": "Los Angeles, CA" }

    Returns up to 3 route options ranked by total fuel cost (cheapest first).
    Each route includes:
      - full fuel stop plan (starting with initial fill-up at start city)
      - total cost, miles, gallons
      - encoded polyline for map rendering
    """

    def post(self, request):
        start = request.data.get("start", "").strip()
        finish = request.data.get("finish", "").strip()

        if not start or not finish:
            return Response(
                {"error": "Both 'start' and 'finish' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        t0 = time.time()

        # Step 1: Geocode start and finish via Nominatim (OpenStreetMap, no API key)
        try:
            start_coords = geocode_location(start)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            finish_coords = geocode_location(finish)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Step 2: Get up to 3 alternative routes in ONE API call
        try:
            route_service = RouteService()
            routes = route_service.get_routes(start_coords, finish_coords)
        except Exception as e:
            return Response(
                {"error": f"Routing API error: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY
            )

        # Step 3: Optimize fuel stops for all routes, rank by cost (no API calls)
        optimizer = FuelOptimizer()
        optimized_routes = optimizer.optimize_all_routes(routes, start_coords)

        elapsed = round(time.time() - t0, 2)

        def build_route_payload(r):
            stops = r["fuel_stops"]

            # ── Start fuel (initial fill-up before the trip begins) ──────────
            start_fuel = None
            first_en_route = None
            remaining_stops = []

            for stop in stops:
                if stop.get("stop_type") == "initial_fillup" and start_fuel is None:
                    start_fuel = {
                        "station_name": stop["name"],
                        "address": stop.get("address", ""),
                        "city": stop["city"],
                        "state": stop["state"],
                        "latitude": stop["latitude"],
                        "longitude": stop["longitude"],
                        "price_per_gallon_usd": stop["retail_price"],
                        "gallons_purchased": stop["gallons_purchased"],
                        "cost_usd": stop["cost_at_stop"],
                        "mile_marker": stop["mile_marker"],
                        "note": (
                            "Tank filled to full at departure. "
                            "This is the minimum spend required to begin the trip."
                        ),
                    }
                elif stop.get("stop_type") == "en_route" and first_en_route is None:
                    first_en_route = stop
                    remaining_stops.append(stop)
                else:
                    remaining_stops.append(stop)

            return {
                
                # ── Prominent top-level fuel highlights ─────────────────────
                "start_fuel": start_fuel,
             
                # ── All stops (initial fill-up + every en-route stop) ────────
                "fuel_stops": stops,
                "summary": {
                    # ── Stops ────────────────────────────────────────────────
                    "total_stops": len(stops),
                    "en_route_stops": len([s for s in stops if s.get("stop_type") == "en_route"]),
                    # ── Distance ─────────────────────────────────────────────
                    "distance_start_to_finish_miles": r["total_miles"],
                    "total_detour_miles": r["total_detour_miles"],
                    "total_distance_traveled_miles": r["total_distance_traveled"],
                    # ── Fuel ─────────────────────────────────────────────────
                    "total_gallons_purchased": r["total_gallons"],
                    "total_detour_gallons_burned": r["total_detour_gallons_burned"],
                    "total_fuel_burned_gallons": r["total_fuel_burned_gallons"],
                    # ── Cost ─────────────────────────────────────────────────
                    "start_fuel_cost_usd": start_fuel["cost_usd"] if start_fuel else 0,
                    "total_fuel_cost_usd": r["total_fuel_cost"],
                    "avg_price_per_gallon": round(
                        r["total_fuel_cost"] / r["total_gallons"], 3
                    ) if r["total_gallons"] else 0,
                },
            }

        return Response({
            "trip": {
                "start": start,
                "finish": finish,
                "start_coords": {"lat": start_coords[0], "lng": start_coords[1]},
                "finish_coords": {"lat": finish_coords[0], "lng": finish_coords[1]},
            },
            # Return only the cheapest optimized route
            "route": build_route_payload(optimized_routes[0]),
            "meta": {
                "response_time_seconds": elapsed,
                "vehicle_range_miles": 500,
                "vehicle_mpg": 10,
                "note": (
                    "Optimal (cheapest) route returned. "
                    "'start_fuel' = initial fill-up at departure (minimum spend to begin the trip). "
                    "'first_fuel_station' = first en-route stop after leaving the start city. "
                    "All monetary values in USD."
                ),
            }
        })