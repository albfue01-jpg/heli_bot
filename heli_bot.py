import os
import time
import threading
import requests
from flask import Flask

BOT_TOKEN = "8713579513:AAFb1KYvwrsJSBTweYCrnd3GuNhPtijdDyg"
CHAT_ID = "5557087140"

WATCHLIST = {
    "4AAA0E": "SE-JPN",
    "4AAA12": "SE-JPR",
    "4AAA0F": "SE-JPO",
    "4AAA13": "SE-JPS",
    "4AAA14": "SE-JPT",
    "4AAA15": "SE-JPU",
    "4AAA16": "SE-JPV",
    "4AAA18": "SE-JPX",
    "4AAA19": "SE-JPY",
}

CHECK_EVERY_SECONDS = 20
last_status = {}

app = Flask(__name__)


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message
    }
    response = requests.post(url, json=data, timeout=15)
    print("Telegram:", response.text)


def get_all_aircraft():
    hex_list = ",".join(WATCHLIST.keys())
    url = f"https://opendata.adsb.fi/api/v2/icao/{hex_list}"
    response = requests.get(url, timeout=15)
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
    except Exception:
        alt = 0

    try:
        gs = float(gs)
    except Exception:
        gs = 0

    return alt >= 200 or gs >= 40


def build_message(ac, reg_name):
    lat = ac.get("lat")
    lon = ac.get("lon")
    alt = ac.get("alt_baro") or ac.get("alt_geom") or ac.get("altitude")
    gs = ac.get("gs") or ac.get("ground_speed")

    return (
        f"🚁 {reg_name} verkar ha lyft\n"
        f"Lat/Lon: {lat}, {lon}\n"
        f"Höjd: {alt} ft\n"
        f"Fart: {gs} kt"
    )


def bot_loop():
    started_message_sent = False

    while True:
        try:
            if not started_message_sent:
                send_telegram("✅ Helikopterboten startade på Render")
                started_message_sent = True

            data = get_all_aircraft()
            aircraft_list = extract_aircraft_list(data)

            seen_hexes = set()

            for ac in aircraft_list:
                hex_code = (ac.get("hex") or ac.get("icao") or ac.get("icao24") or "").upper()
                if not hex_code or hex_code not in WATCHLIST:
                    continue

                seen_hexes.add(hex_code)

                reg_name = WATCHLIST[hex_code]
                current_airborne = is_airborne(ac)
                previous_airborne = last_status.get(hex_code, False)

                if current_airborne and not previous_airborne:
                    send_telegram(build_message(ac, reg_name))
                    print(f"Skickade notis för {reg_name}")

                last_status[hex_code] = current_airborne

            for hex_code in WATCHLIST:
                if hex_code not in seen_hexes:
                    last_status[hex_code] = False

        except Exception as e:
            print("Fel:", e)

        time.sleep(CHECK_EVERY_SECONDS)


@app.route("/")
def home():
    return "Heli bot is running"


if __name__ == "__main__":
    thread = threading.Thread(target=bot_loop, daemon=True)
    thread.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)