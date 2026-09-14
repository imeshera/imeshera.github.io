#!/usr/bin/env python3
"""Attach a city-level location to Wahoo workouts from cached values or FIT GPS."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVITIES = ROOT / "wahoo-activities.json"
MAX_NEW_GEOCODES = 40
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "imeshera.github.io/1.0 (workout location; ieshera@vt.edu)"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def previous_locations(previous_path: Path | None) -> dict[int, str]:
    data = load_json(previous_path) if previous_path else {}
    out = {}
    for workout in data.get("workouts") or []:
        location = (workout.get("location") or "").strip()
        if location and workout.get("id") is not None:
            out[int(workout["id"])] = location
    return out


def semicircles_to_degrees(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if abs(number) > 180:
        number = number * (180.0 / 2**31)
    if abs(number) > 90 and abs(number) <= 180:
        # longitude-only values can be up to 180
        return number
    if abs(number) > 180:
        return None
    return number


def start_coords_from_fit(path: Path) -> tuple[float, float] | None:
    try:
        from fitparse import FitFile
    except ImportError:
        print("fitparse is not installed; skipping GPS lookup", file=sys.stderr)
        return None

    fit = FitFile(str(path))
    for message_name in ("session", "record", "event"):
        for message in fit.get_messages(message_name):
            lat = message.get_value("start_position_lat")
            lon = message.get_value("start_position_long")
            if lat is None or lon is None:
                lat = message.get_value("position_lat")
                lon = message.get_value("position_long")
            lat = semicircles_to_degrees(lat)
            lon = semicircles_to_degrees(lon)
            if lat is None or lon is None:
                continue
            if abs(lat) > 90 or abs(lon) > 180:
                continue
            if lat == 0 and lon == 0:
                continue
            return lat, lon
    return None


def download_fit(url: str, token: str, dest: Path) -> bool:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "*/*",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            dest.write_bytes(response.read())
        return dest.stat().st_size > 0
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"FIT download failed: {exc}", file=sys.stderr)
        return False


def format_address(address: dict) -> str:
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or address.get("county")
    )
    if not city:
        return ""

    country_code = (address.get("country_code") or "").upper()
    if country_code == "US":
        iso = address.get("ISO3166-2-lvl4") or ""
        state = iso.split("-")[-1] if "-" in iso else address.get("state")
        return f"{city}, {state}" if state else city

    country = address.get("country")
    return f"{city}, {country}" if country else city


def reverse_geocode(lat: float, lon: float) -> str:
    query = urllib.parse.urlencode(
        {
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "format": "jsonv2",
            "zoom": 10,
            "addressdetails": 1,
        }
    )
    request = urllib.request.Request(
        f"{NOMINATIM}?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Geocode failed: {exc}", file=sys.stderr)
        return ""
    return format_address(payload.get("address") or {})


def timezone_location(time_zone: str | None) -> str:
    # Only use timezones whose last component is a real city, not a region.
    city_zones = {
        "Africa/Cairo": "Cairo, Egypt",
        "America/Los_Angeles": "Los Angeles, CA",
        "America/New_York": "",
        "America/Chicago": "",
        "America/Denver": "",
    }
    if not time_zone:
        return ""
    if time_zone in city_zones:
        return city_zones[time_zone]
    return ""


def enrich(previous_path: Path | None) -> int:
    data = load_json(ACTIVITIES)
    workouts = data.get("workouts") or []
    cached = previous_locations(previous_path)
    token = os.environ.get("ACCESS_TOKEN") or os.environ.get("WAHOO_ACCESS_TOKEN") or ""
    added = 0

    for workout in workouts:
        workout_id = workout.get("id")
        if workout.get("location"):
            continue
        if workout_id in cached:
            workout["location"] = cached[workout_id]
            continue

        summary = workout.get("workout_summary") or {}
        fallback = timezone_location(summary.get("time_zone"))
        fit_url = ((summary.get("file") or {}).get("url") or "").strip()

        if token and fit_url and added < MAX_NEW_GEOCODES:
            with tempfile.TemporaryDirectory() as tmp:
                fit_path = Path(tmp) / "workout.fit"
                if download_fit(fit_url, token, fit_path):
                    coords = start_coords_from_fit(fit_path)
                    if coords:
                        location = reverse_geocode(*coords)
                        time.sleep(1.1)
                        if location:
                            workout["location"] = location
                            added += 1
                            continue

        if fallback:
            workout["location"] = fallback

    ACTIVITIES.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Geocoded {added} new workout location(s)")
    return 0


if __name__ == "__main__":
    previous = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    raise SystemExit(enrich(previous))
