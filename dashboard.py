#!/usr/bin/env python3
"""PLACASLOPEZ - Dashboard local. Uso: python3 dashboard.py  (abre http://127.0.0.1:8765)"""
import json, os, sys, threading, time, webbrowser, urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tesla  # noqa: E402

PORT = 8765
HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")


def api(method, path, data=None):
    return tesla.req(method, f"{tesla.API}/api/1/energy_sites/{tesla.site_id()}{path}", data, token=tesla.token())


def today_totals():
    """Totales del dia en kWh (si Tesla los ofrece)."""
    try:
        q = urllib.parse.urlencode({"kind": "energy", "period": "day", "time_zone": "America/Puerto_Rico",
                                    "end_date": datetime.now().astimezone().isoformat(timespec="seconds")})
        ts = api("GET", f"/calendar_history?{q}")["response"].get("time_series", [])
        s = lambda *keys: round(sum(sum(r.get(k, 0) or 0 for k in keys) for r in ts) / 1000, 1)
        t = {"solar": s("solar_energy_exported"),
                "importado": s("grid_energy_imported"),
                "exportado": s("grid_energy_exported_from_solar", "grid_energy_exported_from_battery",
                               "grid_energy_exported_from_generator"),
                "bateria": s("battery_energy_exported"),
                "casa": s("consumer_energy_imported_from_grid", "consumer_energy_imported_from_solar",
                          "consumer_energy_imported_from_battery", "consumer_energy_imported_from_generator")}
        if not t["casa"]:
            t["casa"] = round(t["solar"] + t["importado"] + t["bateria"] - t["exportado"], 1)
        return t
    except (SystemExit, Exception):
        return None


def status():
    live = api("GET", "/live_status")["response"]
    info = api("GET", "/site_info")["response"]
    return {"live": live, "modo": info.get("default_real_mode"),
            "reserva": info.get("backup_reserve_percent"), "nombre": info.get("site_name"),
            "hoy": today_totals(), "hora": datetime.now().strftime("%I:%M:%S %p")}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def guarded(self, fn):
        try:
            self.send(200, fn())
        except SystemExit as e:
            self.send(500, {"error": str(e)})
        except Exception as e:
            self.send(500, {"error": repr(e)})

    def do_GET(self):
        if self.path == "/":
            with open(HTML, "rb") as f:
                self.send(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self.guarded(status)
        else:
            self.send(404, {"error": "no encontrado"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        d = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/modo" and d.get("modo") in ("self_consumption", "autonomous"):
            self.guarded(lambda: api("POST", "/operation", {"default_real_mode": d["modo"]}))
        elif self.path == "/api/reserva" and 0 <= int(d.get("reserva", -1)) <= 100:
            self.guarded(lambda: api("POST", "/backup", {"backup_reserve_percent": int(d["reserva"])}))
        else:
            self.send(400, {"error": "pedido invalido"})


if __name__ == "__main__":
    if not os.path.exists(tesla.FILE):
        sys.exit("Primero corre: python3 tesla.py setup")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Dashboard en {url}  (Ctrl+C para cerrar)")
    threading.Timer(1, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")
