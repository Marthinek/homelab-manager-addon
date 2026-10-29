import html
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = os.environ["HOMELAB_API_URL"].rstrip("/")
API_KEY = os.environ["HOMELAB_API_KEY"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return

        devices = []
        error = None
        try:
            request = Request(
                API_URL + "/api/devices",
                headers={"X-API-Key": API_KEY},
            )
            with urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                devices = data.get("devices", [])
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            error = f"API není dostupné nebo požadavek selhal: {type(exc).__name__}"

        rows = ""
        for device in devices:
            rows += (
                "<tr>"
                f"<td>{html.escape(str(device.get('id', '')))}</td>"
                f"<td>{html.escape(str(device.get('role', 'unknown')))}</td>"
                f"<td>{html.escape(str(device.get('os_family', 'unknown')))}</td>"
                f"<td>{html.escape(str(device.get('update_policy', 'manual_approval')))}</td>"
                "</tr>"
            )

        message = (
            f"<p class='error'>{html.escape(error)}</p>"
            if error else f"<p>Počet zařízení: {len(devices)}</p>"
        )
        page = f"""<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Homelab Manager</title>
<style>
body{{font-family:Arial,sans-serif;margin:24px;color:var(--primary-text-color,#222);
background:var(--primary-background-color,#fff)}}
table{{border-collapse:collapse;width:100%;margin-top:16px}}
th,td{{padding:10px;text-align:left;border-bottom:1px solid #8885}}
.error{{color:#c62828}}
small{{opacity:.75}}
</style>
</head>
<body>
<h1>Homelab Manager</h1>
{message}
<table>
<thead><tr><th>Zařízení</th><th>Role</th><th>OS</th><th>Politika aktualizací</th></tr></thead>
<tbody>{rows or '<tr><td colspan="4">Zatím žádná zařízení nebo se nepodařilo načíst data.</td></tr>'}</tbody>
</table>
<p><small>Aktualizace přehledu každých 60 sekund. Tento doplněk zatím pouze čte inventář.</small></p>
</body>
</html>"""
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("Homelab Manager UI:", fmt % args)


HTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
