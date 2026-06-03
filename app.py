import argparse
import json
import math
import random
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    import serial
except ImportError:
    serial = None


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


def now_stamp():
    return time.strftime("%H:%M:%S")


def read_field(packet, key):
    start = packet.find(key)
    if start < 0:
        return ""
    start += len(key)
    end = packet.find("|", start)
    if end < 0:
        end = len(packet)
    return packet[start:end].strip()


def clean_battery(value):
    return value.replace("%", "").strip()


def signal_quality(rssi):
    try:
        value = int(float(rssi))
    except ValueError:
        return "NO LINK"
    if value >= -70:
        return "GOOD"
    if value >= -90:
        return "FAIR"
    return "WEAK"


def parse_gps(value):
    if not value or "," not in value or "NO_GPS" in value:
        return None
    lat, lon = value.split(",", 1)
    try:
        return float(lat), float(lon)
    except ValueError:
        return None


def parse_packet(packet):
    packet = packet.strip()
    if packet.startswith("TELEMETRY_PACKET:"):
        packet = packet.split(":", 1)[1].strip()

    lat = read_field(packet, "LAT:")
    lon = read_field(packet, "LON:")
    user_gps = read_field(packet, "USER_GPS:")
    payload_gps = read_field(packet, "PAYLOAD_GPS:")
    payload_lat = read_field(packet, "PAYLOAD_LAT:")
    payload_lon = read_field(packet, "PAYLOAD_LON:")
    rssi = read_field(packet, "RSSI:")
    signal = read_field(packet, "SIGNAL:")

    if not user_gps and lat and lon:
        user_gps = f"{lat},{lon}"
    if not payload_gps and payload_lat and payload_lon:
        payload_gps = f"{payload_lat},{payload_lon}"
    if not signal:
        signal = signal_quality(rssi)

    return {
        "raw": packet,
        "lat": lat,
        "lon": lon,
        "userGps": user_gps or "0,0",
        "payloadGps": payload_gps or "0,0",
        "battery": clean_battery(read_field(packet, "BATTERY:") or "0"),
        "temp": read_field(packet, "TEMP:") or "0",
        "rssi": rssi or "0",
        "signal": signal,
        "mission": read_field(packet, "MISSION:") or "STANDBY",
        "alert": read_field(packet, "ALERT:") or "WAITING",
        "message": read_field(packet, "MSG:") or "",
        "payloadTime": read_field(packet, "TIME:") or "00:00:00",
        "lastCommand": read_field(packet, "LASTCMD:") or "IDLE",
        "commandStatus": read_field(packet, "CMD_STATUS:") or "WAITING",
        "externalLight": read_field(packet, "EXT_LIGHT:") or "OFF",
        "receivedAt": now_stamp(),
    }


class TelemetryStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.started_at = time.time()
        self.packet_count = 0
        self.raw_lines = []
        self.events = []
        self.route = []
        self.rssi_history = []
        self.battery_history = []
        self.temp_history = []
        self.latest = parse_packet(
            "LAT:17.7104743|LON:83.1659175|USER_GPS:0,0|PAYLOAD_GPS:17.7104743,83.1659175|BATTERY:0%|TEMP:0|RSSI:0|SIGNAL:NO LINK|MISSION:STANDBY|ALERT:WAITING|MSG:BOOT"
        )

    def add_line(self, line):
        line = line.strip()
        if not line:
            return

        with self.lock:
            self.raw_lines.append({"time": now_stamp(), "line": line})
            self.raw_lines = self.raw_lines[-160:]

        if "LAT:" not in line or "LON:" not in line:
            return

        packet = parse_packet(line)
        gps = parse_gps(packet["payloadGps"]) or parse_gps(f"{packet['lat']},{packet['lon']}")

        with self.lock:
            self.packet_count += 1
            self.latest = packet
            if gps:
                point = {
                    "lat": gps[0],
                    "lon": gps[1],
                    "time": packet["receivedAt"],
                    "rssi": packet["rssi"],
                    "signal": packet["signal"],
                }
                self.route.append(point)
                self.route = self.route[-500:]

            self.events.insert(0, {
                "time": packet["receivedAt"],
                "mission": packet["mission"],
                "alert": packet["alert"],
                "signal": packet["signal"],
                "message": packet["message"],
            })
            self.events = self.events[:100]

            self.rssi_history.append({"time": packet["receivedAt"], "value": self._to_float(packet["rssi"])})
            self.battery_history.append({"time": packet["receivedAt"], "value": self._to_float(packet["battery"])})
            self.temp_history.append({"time": packet["receivedAt"], "value": self._to_float(packet["temp"])})
            self.rssi_history = self.rssi_history[-80:]
            self.battery_history = self.battery_history[-80:]
            self.temp_history = self.temp_history[-80:]

    def snapshot(self):
        with self.lock:
            rssi_values = [x["value"] for x in self.rssi_history if x["value"] is not None]
            avg_rssi = round(sum(rssi_values) / len(rssi_values), 1) if rssi_values else 0
            uptime = int(time.time() - self.started_at)
            return {
                "latest": self.latest,
                "packets": self.packet_count,
                "uptime": uptime,
                "route": list(self.route),
                "events": list(self.events),
                "rawLines": list(self.raw_lines),
                "history": {
                    "rssi": list(self.rssi_history),
                    "battery": list(self.battery_history),
                    "temp": list(self.temp_history),
                },
                "analytics": {
                    "avgRssi": avg_rssi,
                    "routePoints": len(self.route),
                    "distanceMeters": round(self._distance(), 1),
                    "online": time.time() - self._last_packet_epoch() < 8 if self.packet_count else False,
                },
            }

    def _last_packet_epoch(self):
        return self.started_at + self.packet_count

    def _distance(self):
        total = 0.0
        for a, b in zip(self.route, self.route[1:]):
            total += haversine(a["lat"], a["lon"], b["lat"], b["lon"])
        return total

    @staticmethod
    def _to_float(value):
        try:
            return float(str(value).replace("%", ""))
        except ValueError:
            return None


def haversine(lat1, lon1, lat2, lon2):
    radius = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def serial_worker(store, port, baud):
    if serial is None:
        store.add_line("SERIAL: pyserial not installed. Simulator is active.")
        simulator_worker(store)
        return

    while True:
        try:
            with serial.Serial(port, baudrate=baud, timeout=1) as device:
                store.add_line(f"SERIAL: connected to {port} at {baud}")
                while True:
                    line = device.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        store.add_line(line)
        except Exception as exc:
            store.add_line(f"SERIAL: reconnecting after error: {exc}")
            time.sleep(2)


def simulator_worker(store):
    base_lat = 17.7104743
    base_lon = 83.1659175
    n = 0
    while True:
        n += 1
        lat = base_lat + math.sin(n / 10) * 0.0015 + n * 0.00002
        lon = base_lon + math.cos(n / 12) * 0.0015 + n * 0.00002
        rssi = -62 - random.randint(0, 42)
        battery = max(15, 96 - n // 5)
        temp = round(28.4 + math.sin(n / 7) * 3, 1)
        alert = "NORMAL"
        mission = "TRACKING"
        if n % 37 == 0:
            alert = "WARNING"
        packet = (
            f"TELEMETRY_PACKET:LAT:{lat:.6f}|LON:{lon:.6f}|USER_GPS:0,0|PAYLOAD_GPS:{lat:.6f},{lon:.6f}"
            f"|BATTERY:{battery}%|TEMP:{temp}|RSSI:{rssi}|SIGNAL:{signal_quality(rssi)}"
            f"|MISSION:{mission}|ALERT:{alert}|MSG:SIM_PACKET_{n}|TIME:{now_stamp()}"
        )
        store.add_line(packet)
        time.sleep(1.5)


class Handler(SimpleHTTPRequestHandler):
    store = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/telemetry":
            body = json.dumps(self.store.snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, *_):
        return


def main():
    parser = argparse.ArgumentParser(description="Dead Zone Killer Ground Station 2")
    parser.add_argument("--port", help="Serial port from Ground Station 1, for example COM5")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8082)
    parser.add_argument("--simulate", action="store_true")
    args = parser.parse_args()

    store = TelemetryStore()
    Handler.store = store

    if args.port and not args.simulate:
        thread = threading.Thread(target=serial_worker, args=(store, args.port, args.baud), daemon=True)
    else:
        thread = threading.Thread(target=simulator_worker, args=(store,), daemon=True)
    thread.start()

    server = ThreadingHTTPServer((args.host, args.http_port), Handler)
    print(f"GROUND STATION 2 running at http://{args.host}:{args.http_port}")
    print("Use --port COMx to connect Ground Station 1 over USB serial.")
    server.serve_forever()


if __name__ == "__main__":
    main()
