
import html
import json
import logging
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = os.environ["HOMELAB_API_URL"].rstrip("/")
API_KEY = os.environ["HOMELAB_API_KEY"]

logger = logging.getLogger("homelab-manager-addon")


def api_request(path, method="GET", timeout=330):
    request = Request(
        API_URL + path,
        headers={
            "X-API-Key": API_KEY,
            "Accept": "application/json",
        },
        method=method,
    )

    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

HA_COMPONENTS = (
    ("home-assistant-os", "Home Assistant OS", "os/info"),
    ("home-assistant-core", "Home Assistant Core", "core/info"),
    ("home-assistant-supervisor", "Home Assistant Supervisor", "supervisor/info"),
)


def supervisor_devices():
    checked = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    devices = []

    for device_id, label, endpoint in HA_COMPONENTS:
        if not SUPERVISOR_TOKEN:
            message = "Chybí SUPERVISOR_TOKEN; ověř oprávnění Supervisor API v konfiguraci doplňku."
            devices.append({
                "id": device_id,
                "os": label,
                "checked": checked,
                "update_count": 0,
                "packages": [message],
                "error": True,
            })
            continue

        try:
            request = Request(
                "http://supervisor/" + endpoint,
                headers={
                    "Authorization": "Bearer " + SUPERVISOR_TOKEN,
                    "Accept": "application/json",
                },
                method="GET",
            )
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))

            if isinstance(payload, dict) and payload.get("result") == "error":
                raise ValueError("Supervisor API returned an error")

            info = payload.get("data", payload) if isinstance(payload, dict) else {}
            if not isinstance(info, dict):
                raise ValueError("Unexpected Supervisor API response")

            version = str(info.get("version") or "neznámá")
            latest = str(info.get("version_latest") or "neznámá")
            update_available = bool(info.get("update_available", False))
            packages = (
                [f"Aktualizace dostupná: {version} → {latest}"]
                if update_available
                else []
            )

            devices.append({
                "id": device_id,
                "os": f"{label} {version}",
                "version": version,
                "version_latest": latest,
                "checked": checked,
                "update_count": 1 if update_available else 0,
                "packages": packages,
            })
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            message = f"Nepodařilo se načíst informace ({type(exc).__name__})."
            devices.append({
                "id": device_id,
                "os": label,
                "checked": checked,
                "update_count": 0,
                "packages": [message],
                "error": True,
            })

    return devices


def render_page(devices, error=None, notice=None):
    total_updates = sum(
        int(device.get("update_count", 0)) for device in devices
    )

    rows = []

    for device in devices:
        device_id = html.escape(str(device.get("id", "unknown")))
        os_name = html.escape(str(device.get("os", "Neznámý OS")))
        checked = html.escape(str(device.get("checked", "Neznámý")))
        count = int(device.get("update_count", 0))
        packages = device.get("packages", [])

        if device.get("error"):
            status = "<strong class='updates'>Chyba</strong>"
        elif count:
            status = f"<strong class='updates'>{count}</strong>"
        else:
            status = "<strong class='ok'>0</strong>"

        if packages:
            package_html = "<ul>" + "".join(
                f"<li><code>{html.escape(str(package))}</code></li>"
                for package in packages
            ) + "</ul>"
        else:
            package_html = "<span class='muted'>Žádné dostupné aktualizace</span>"

        rows.append(
            "<tr>"
            f"<td><strong>{device_id}</strong></td>"
            f"<td>{os_name}</td>"
            f"<td>{status}</td>"
            f"<td>{checked}</td>"
            f"<td>{package_html}</td>"
            "</tr>"
        )

    error_html = (
        f"<div class='error'>{html.escape(error)}</div>" if error else ""
    )
    notice_html = (
        f"<div class='notice'>{html.escape(notice)}</div>" if notice else ""
    )

    page = f"""<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Homelab Manager</title>
<style>
:root {{
  color-scheme: light dark;
  --border: #8885;
  --panel: #8881;
  --green: #2e9d58;
  --red: #d64545;
  --blue: #287ac2;
}}
body {{
  font-family: Arial, sans-serif;
  margin: 20px;
  color: var(--primary-text-color, inherit);
  background: var(--primary-background-color, transparent);
}}
h1 {{ margin-bottom: 8px; }}
.summary {{
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin: 20px 0;
}}
.card {{
  padding: 14px 18px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel);
  min-width: 110px;
}}
.number {{ display: block; font-size: 1.7em; font-weight: bold; }}
button {{
  background: var(--blue);
  color: white;
  border: 0;
  border-radius: 8px;
  padding: 12px 18px;
  font-size: 1em;
  cursor: pointer;
}}
table {{ border-collapse: collapse; width: 100%; margin-top: 18px; }}
th, td {{
  padding: 12px;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--border);
}}
th {{ background: var(--panel); }}
.updates {{ color: var(--red); }}
.ok {{ color: var(--green); }}
.error, .notice {{
  padding: 12px;
  margin: 14px 0;
  border-radius: 8px;
}}
.error {{ color: var(--red); border: 1px solid var(--red); }}
.notice {{ border: 1px solid var(--green); }}
code {{ overflow-wrap: anywhere; white-space: normal; }}
ul {{ padding-left: 20px; margin: 0; }}
li {{ margin-bottom: 8px; }}
.muted, small {{ opacity: .7; }}
.table-wrap {{ overflow-x: auto; }}
</style>
</head>
<body>
<h1>Homelab Manager</h1>
<p class="muted">Přehled zařízení a dostupných aktualizací operačních systémů.</p>
{error_html}
{notice_html}
<div class="summary">
  <div class="card">
    <span class="muted">Zařízení</span>
    <span class="number">{len(devices)}</span>
  </div>
  <div class="card">
    <span class="muted">Dostupné aktualizace</span>
    <span class="number">{total_updates}</span>
  </div>
</div>
<form method="post" action="/check">
  <button type="submit">Zkontrolovat aktualizace</button>
</form>
<div class="table-wrap">
<table>
<thead>
<tr>
  <th>Zařízení</th>
  <th>Operační systém</th>
  <th>Aktualizace</th>
  <th>Poslední kontrola</th>
  <th>Dostupné balíčky</th>
</tr>
</thead>
<tbody>
{''.join(rows) or '<tr><td colspan="5">Zatím nejsou k dispozici žádné výsledky.</td></tr>'}
</tbody>
</table>
</div>
<p><small>Kontrola pouze zjišťuje dostupné aktualizace. Balíčky neinstaluje a zařízení nerestartuje.</small></p>
</body>
</html>"""

    return page


class Handler(BaseHTTPRequestHandler):
    def send_html(self, page, status=200):
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return

        try:
            data = api_request("/api/updates", timeout=15)
            devices = data.get("devices", [])
            devices.extend(supervisor_devices())
            page = render_page(devices)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("Could not load updates: %s", type(exc).__name__)
            page = render_page(
                [],
                error="Nepodařilo se načíst data z API. Zkontroluj API a konfiguraci doplňku.",
            )

        self.send_html(page)

    def do_POST(self):
        if self.path != "/check":
            self.send_error(404)
            return

        try:
            data = api_request(
                "/api/updates/check",
                method="POST",
                timeout=330,
            )
            devices = data.get("devices", [])
            devices.extend(supervisor_devices())
            total_updates = sum(int(device.get("update_count", 0)) for device in devices)
            notice = (
                "Kontrola dokončena. "
                f"Zobrazené položky: {len(devices)}, "
                f"dostupné aktualizace: {total_updates}."
            )
            page = render_page(devices, notice=notice)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("Update check failed: %s", type(exc).__name__)
            try:
                data = api_request("/api/updates", timeout=15)
                devices = data.get("devices", [])
                devices.extend(supervisor_devices())
            except (HTTPError, URLError, TimeoutError, ValueError, OSError):
                devices = []

            page = render_page(
                devices,
                error="Kontrola aktualizací selhala. Zkontroluj logy API a doplňku.",
            )

        self.send_html(page)

    def log_message(self, fmt, *args):
        logger.info("%s", fmt % args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server = ThreadingHTTPServer(("0.0.0.0", 8099), Handler)
    logger.info("Homelab Manager add-on listening on port 8099")
    server.serve_forever()
