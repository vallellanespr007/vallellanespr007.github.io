#!/usr/bin/env python3
"""PLACASLOPEZ - Tesla Fleet API (Powerwall / solar).

Solo usa la libreria estandar de Python. Uso:
    python3 tesla.py setup     # una sola vez: registra el dominio y autoriza tu cuenta
    python3 tesla.py status    # estado en vivo (solar, casa, red, bateria)
    python3 tesla.py modo self_consumption|autonomous
    python3 tesla.py reserva 30
"""
import getpass, json, os, sys, time, urllib.parse, urllib.request, webbrowser, secrets

DOMAIN = "vallellanespr007.github.io"
REDIRECT = f"https://{DOMAIN}/callback"
AUTH = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3"
API = "https://fleet-api.prd.na.vn.cloud.tesla.com"
SCOPES = "openid offline_access energy_device_data energy_cmds"
FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tesla_tokens.json")


def req(method, url, data=None, token=None, form=False):
    headers = {"Accept": "application/json"}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"Error {e.code} en {url}:\n{e.read().decode(errors='replace')}")


def load():
    if not os.path.exists(FILE):
        sys.exit("Primero corre: python3 tesla.py setup")
    with open(FILE) as f:
        return json.load(f)


def save(d):
    with open(FILE, "w") as f:
        json.dump(d, f, indent=2)
    try:
        os.chmod(FILE, 0o600)
    except OSError:
        pass


def token():
    d = load()
    if time.time() < d.get("expires_at", 0) - 60:
        return d["access_token"]
    t = req("POST", f"{AUTH}/token", {
        "grant_type": "refresh_token", "client_id": d["client_id"],
        "refresh_token": d["refresh_token"]}, form=True)
    d.update(access_token=t["access_token"], refresh_token=t.get("refresh_token", d["refresh_token"]),
             expires_at=time.time() + t.get("expires_in", 28800))
    save(d)
    return d["access_token"]


def setup():
    cid = input("Client ID: ").strip()
    secret = getpass.getpass("Client Secret (no se ve al escribir): ").strip()

    print("\n1) Registrando el dominio con Tesla...")
    p = req("POST", f"{AUTH}/token", {
        "grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
        "scope": SCOPES, "audience": API}, form=True)
    req("POST", f"{API}/api/1/partner_accounts", {"domain": DOMAIN}, token=p["access_token"])
    print("   Dominio registrado.")

    print("\n2) Autoriza tu cuenta de Tesla en el navegador.")
    state = secrets.token_urlsafe(16)
    url = "https://auth.tesla.com/oauth2/v3/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT,
        "scope": SCOPES, "state": state, "prompt_missing_scopes": "true"})
    print("   Si no abre solo, copia este link:\n  ", url)
    webbrowser.open(url)
    code = input("\n   Pega aqui el codigo que muestra la pagina: ").strip()

    t = req("POST", f"{AUTH}/token", {
        "grant_type": "authorization_code", "client_id": cid, "client_secret": secret,
        "code": code, "audience": API, "redirect_uri": REDIRECT}, form=True)
    save({"client_id": cid, "access_token": t["access_token"], "refresh_token": t["refresh_token"],
          "expires_at": time.time() + t.get("expires_in", 28800)})
    print("\n3) Listo. Tokens guardados en tesla_tokens.json (no lo subas a GitHub).")
    status()


def site_id():
    d = load()
    if d.get("site_id"):
        return d["site_id"]
    prods = req("GET", f"{API}/api/1/products", token=token())["response"]
    sites = [p for p in prods if "energy_site_id" in p]
    if not sites:
        sys.exit("No encontre ningun sistema de energia en esta cuenta.")
    for s in sites:
        print(f"   Sitio: {s.get('site_name')} (id {s['energy_site_id']})")
    d = load()
    d["site_id"] = sites[0]["energy_site_id"]
    save(d)
    return d["site_id"]


def status():
    sid = site_id()
    s = req("GET", f"{API}/api/1/energy_sites/{sid}/live_status", token=token())["response"]
    kw = lambda w: f"{(w or 0) / 1000:.1f} kW"
    grid = s.get("grid_power", 0) or 0
    print(f"""
   Solar:     {kw(s.get('solar_power'))}
   Casa:      {kw(s.get('load_power'))}
   Red LUMA:  {kw(abs(grid))} {'(comprando)' if grid > 0 else '(exportando)' if grid < 0 else ''}
   Powerwall: {kw(s.get('battery_power'))} - {s.get('percentage_charged', 0):.0f}%
   Red activa: {s.get('grid_status')}""")


def modo(m):
    if m not in ("self_consumption", "autonomous"):
        sys.exit("Usa: self_consumption (Self-Powered) o autonomous (Time-Based Control)")
    r = req("POST", f"{API}/api/1/energy_sites/{site_id()}/operation", {"default_real_mode": m}, token=token())
    print("Modo cambiado:", r)


def reserva(p):
    r = req("POST", f"{API}/api/1/energy_sites/{site_id()}/backup", {"backup_reserve_percent": int(p)}, token=token())
    print("Reserva cambiada:", r)


if __name__ == "__main__":
    a = sys.argv[1:] or ["status"]
    {"setup": lambda: setup(), "status": lambda: status(),
     "modo": lambda: modo(a[1]), "reserva": lambda: reserva(a[1])}.get(a[0], lambda: print(__doc__))()
