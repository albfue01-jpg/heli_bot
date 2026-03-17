import os
import csv
import math
import time
import threading
import requests
from flask import Flask

BOT_TOKEN = "8713579513:AAFb1KYvwrsJSBTweYCrnd3GuNhPtijdDyg"
CHAT_ID = "5557087140"

WATCHLIST = {
    "4AAA0E": "Polishelikopter SE-JPN",
    "4AAA12": "Polishelikopter SE-JPR",
    "4AAA0F": "Polishelikopter SE-JPO",
    "4AAA13": "Polishelikopter SE-JPS",
    "4AAA14": "Polishelikopter SE-JPT",
    "4AAA15": "Polishelikopter SE-JPU",
    "4AAA16": "Polishelikopter SE-JPV",
    "4AAA18": "Polishelikopter SE-JPX",
    "4AAA19": "Polishelikopter SE-JPY",
}

CHECK_EVERY_SECONDS = 30
TAKEOFF_ALTITUDE_FEET = 200
TAKEOFF_GROUNDSPEED_KNOTS = 40

last_status = {}
city_state = {}

app = Flask(__name__)


def load_cities(filename="city.csv"):
    cities = []

    with open(filename, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        for row in reader:
            if len(row) < 6:
                continue

            try:
                name = row[0].strip()
                municipality = row[1].strip()
                county = row[2].strip()
                lat = float(row[3])
                lon = float(row[4])
                radius = float(row[5])
            except (ValueError, IndexError):
                continue

            if not name:
                continue

            label = name
            if municipality and municipality.lower() != name.lower():
                label = f"{name} ({municipality})"

            cities.append({
                "name": name,
                "municipality": municipality,
                "county": county,
                "label": label,
                "lat": lat,
                "lon": lon,
                "radius": radius
            })

    print(f"Laddade {len(cities)} orter från {filename}")
    return cities


CITIES = load_cities("city.csv")


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message
    }

    response = requests.post(url, json=data, timeout=20)
    response.raise_for_status()
    print("Telegram skickat:", message.split("\n")[0])


def get_all_aircraft():
    hex_list = ",".join(WATCHLIST.keys())
    url = f"https://opendata.adsb.fi/api/v2/icao/{hex_list}"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


def extract_aircraft_list(data):
    if isinstance(data, dict):
        if "ac" in data:
            return data["ac"]
        if "aircraft" in data:
            return data["aircraft"]
    if isinstance(data, list):
        return data
    return []


def is_airborne(ac):
    alt = ac.get("alt_baro") or ac.get("alt_geom") or ac.get("altitude") or 0
    gs = ac.get("gs") or ac.get("ground_speed") or 0
    on_ground = ac.get("on_ground")

    if on_ground is True:
        return False

    try:
        alt = float(alt)
    except (TypeError, ValueError):
        alt = 0

    try:
        gs = float(gs)
    except (TypeError, ValueError):
        gs = 0

    return alt >= TAKEOFF_ALTITUDE_FEET or gs >= TAKEOFF_GROUNDSPEED_KNOTS


def distance_km(lat1, lon1, lat2, lon2):
    r = 6371.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )

    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_matching_cities(ac):
    lat = ac.get("lat")
    lon = ac.get("lon")

    if lat is None or lon is None:
        return []

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return []

    matches = []

    for city in CITIES:
        dist = distance_km(lat, lon, city["lat"], city["lon"])
        if dist <= city["radius"]:
            matches.append((dist, city))

    matches.sort(key=lambda x: x[0])
    return [city for dist, city in matches]


def maps_link(lat, lon):
    return f"https://maps.google.com/?q={lat},{lon}"


def build_takeoff_message(ac, heli_name):
    lat = ac.get("lat")
    lon = ac.get("lon")
    alt = ac.get("alt_baro") or ac.get("alt_geom") or ac.get("altitude")
    gs = ac.get("gs") or ac.get("ground_speed")
    cities = get_matching_cities(ac)

    place_line = ""
    if cities:
        place_line = f"Över: {cities[0]['label']}\n"

    map_line = ""
    if lat is not None and lon is not None:
        map_line = f"Karta: {maps_link(lat, lon)}\n"

    return (
        f"🚁 {heli_name} lyfte\n"
        f"{place_line}"
        f"Höjd: {alt} ft\n"
        f"Fart: {gs} kt\n"
        f"Position: {lat}, {lon}\n"
        f"{map_line}"
    ).strip()


def build_city_message(heli_name, city, ac):
    lat = ac.get("lat")
    lon = ac.get("lon")
    alt = ac.get("alt_baro") or ac.get("alt_geom") or ac.get("altitude")
    gs = ac.get("gs") or ac.get("ground_speed")

    map_line = ""
    if lat is not None and lon is not None:
        map_line = f"\nKarta: {maps_link(lat, lon)}"

    return (
        f"🏙️ {heli_name} flyger över {city['label']}\n"
        f"Höjd: {alt} ft\n"
        f"Fart: {gs} kt{map_line}"
    )


def bot_loop():
    start_message_sent = False

    while True:
        try:
            if not start_message_sent:
                send_telegram("✅ Polishelikopter-bevakningen är igång")
                start_message_sent = True

            data = get_all_aircraft()
            aircraft_list = extract_aircraft_list(data)
            seen_hexes = set()

            for ac in aircraft_list:
                hex_code = (ac.get("hex") or ac.get("icao") or ac.get("icao24") or "").upper()
                if not hex_code or hex_code not in WATCHLIST:
                    continue

                seen_hexes.add(hex_code)
                heli_name = WATCHLIST[hex_code]

                current_airborne = is_airborne(ac)
                previous_airborne = last_status.get(hex_code, False)

                if current_airborne and not previous_airborne:
                    send_telegram(build_takeoff_message(ac, heli_name))

                last_status[hex_code] = current_airborne

                matching_cities = get_matching_cities(ac)
                active_city_keys = set()

                for city in matching_cities:
                    city_key = f"{hex_code}:{city['label']}"
                    active_city_keys.add(city_key)

                    if not city_state.get(city_key, False):
                        send_telegram(build_city_message(heli_name, city, ac))
                        city_state[city_key] = True

                for key in list(city_state.keys()):
                    if key.startswith(f"{hex_code}:") and key not in active_city_keys:
                        city_state[key] = False

            for hex_code in WATCHLIST:
                if hex_code not in seen_hexes:
                    last_status[hex_code] = False

        except Exception as e:
            print("Fel:", e)

        time.sleep(CHECK_EVERY_SECONDS)


@app.route("/")
def home():
    return "Polishelikopter-bevakningen körs"


if __name__ == "__main__":
    thread = threading.Thread(target=bot_loop, daemon=True)
    thread.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)