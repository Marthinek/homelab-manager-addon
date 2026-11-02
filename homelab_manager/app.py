
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


def api_request(path, method="GET", timeout=330, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "X-API-Key": API_KEY,
        "Accept": "application/json",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        API_URL + path,
        data=body,
        headers=headers,
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


def render_page(devices, error=None, notice=None, system_filter="all"):
    total_updates = sum(
        int(device.get("update_count", 0)) for device in devices
    )
    devices_with_updates = sum(
        1 for device in devices
        if int(device.get("update_count", 0)) > 0 and not device.get("error")
    )
    device_errors = sum(1 for device in devices if device.get("error"))

    def device_system(device):
        os_name = str(device.get("os", "")).lower()
        device_id = str(device.get("id", "")).lower()

        if "openwrt" in os_name:
            return "openwrt"
        if "proxmox" in os_name or "pve" in device_id:
            return "proxmox"
        if "debian" in os_name:
            return "debian"
        if "home assistant" in os_name or any(
            name in device_id for name in ("homeassistant", "home-assistant")
        ):
            return "homeassistant"
        return "other"

    filtered_devices = [
        device for device in devices
        if system_filter == "all" or device_system(device) == system_filter
    ]

    rows = []

    for device in filtered_devices:
        device_id = html.escape(str(device.get("id", "unknown")))
        os_name = html.escape(str(device.get("os", "Neznámý OS")))
        checked = html.escape(str(device.get("checked", "Neznámý")))
        count = int(device.get("update_count", 0))
        packages = device.get("packages", [])

        if device.get("error"):
            status = "<span class='status-pill status-error'>Chyba</span>"
        elif count:
            status = f"<span class='status-pill status-updates'>{count} aktualizací</span>"
        else:
            status = "<span class='status-pill status-ok'>Aktuální</span>"

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

    update_choices = []
    for device in filtered_devices:
        device_id_raw = str(device.get("id", ""))
        count = int(device.get("update_count", 0))
        if device.get("can_update"):
            update_choices.append(
                "<label class='update-choice'>"
                f"<input type='checkbox' name='hosts' value='{html.escape(device_id_raw, quote=True)}' "
                f"{'checked' if count > 0 else ''}> "
                f"<span><strong>{html.escape(device_id_raw)}</strong>"
                f"<small>{count} dostupných aktualizací</small></span>"
                "</label>"
            )
        else:
            reason = html.escape(str(device.get("update_reason", "Tento typ není podporován.")))
            update_choices.append(
                "<label class='update-choice disabled'>"
                f"<input type='checkbox' disabled> "
                f"<span><strong>{html.escape(device_id_raw)}</strong>"
                f"<small>{count} aktualizací · {reason}</small></span>"
                "</label>"
            )

    update_modal = "".join(update_choices) or "<p>Pro tento filtr nejsou dostupná žádná zařízení.</p>"

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
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 20px 0;
}}
.card {{
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--card-background-color, var(--panel));
  min-width: 0;
  box-shadow: 0 2px 8px #0000000a;
}}
.card-label {{ display: block; font-size: .88em; opacity: .75; margin-bottom: 8px; }}
.number {{ display: block; font-size: 1.9em; font-weight: 700; line-height: 1.1; }}
.card-detail {{ display: block; margin-top: 7px; font-size: .8em; opacity: .65; }}
.status-pill {{
  display: inline-block;
  padding: 4px 9px;
  border-radius: 999px;
  font-size: .82em;
  font-weight: 700;
  white-space: nowrap;
}}
.status-updates {{ color: var(--error-color, #d64545); background: #d6454518; }}
.status-ok {{ color: var(--success-color, #2e9d58); background: #2e9d5818; }}
.status-error {{ color: var(--error-color, #d64545); background: #d6454520; }}
.toolbar {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin: 20px 0 10px;
}}
select {{
  color: var(--primary-text-color, inherit);
  background: var(--card-background-color, var(--panel));
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 1em;
}}
table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
th, td {{
  padding: 12px;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--border);
}}
th {{ background: var(--panel); font-size: .86em; opacity: .8; }}
tbody tr:hover {{ background: var(--panel); }}
@media (max-width: 700px) {{
  body {{ margin: 12px; }}
  .summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
  .card {{ padding: 12px; }}
  .number {{ font-size: 1.55em; }}
  th, td {{ padding: 9px; }}
}}
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
dialog {{ width: min(620px, calc(100% - 32px)); max-height: 85vh; overflow: auto; border: 1px solid var(--border); border-radius: 14px; background: var(--card-background-color, var(--primary-background-color, #222)); color: var(--primary-text-color, inherit); padding: 20px; }}
dialog::backdrop {{ background: #0009; }}
.update-choice {{ display: flex; gap: 10px; align-items: flex-start; padding: 10px 0; border-bottom: 1px solid var(--border); }}
.update-choice input {{ margin-top: 4px; }}
.update-choice span {{ display: flex; flex-direction: column; gap: 4px; }}
.update-choice small {{ opacity: .7; }}
.update-choice.disabled {{ opacity: .6; }}
.modal-actions {{ display: flex; gap: 10px; justify-content: flex-end; flex-wrap: wrap; margin-top: 18px; }}
button.secondary {{ background: #777; }}
ul {{ padding-left: 20px; margin: 0; }}
li {{ margin-bottom: 8px; }}
.muted, small {{ opacity: .7; }}
.table-wrap {{ overflow-x: auto; }}
</style>
</head>
<body>
<header>
<h1>Homelab Manager</h1>
<p class="muted">Centrální přehled zařízení a dostupných aktualizací.</p>
</header>
{error_html}
{notice_html}
<div class="summary">
  <div class="card">
    <span class="card-label">Spravovaná zařízení</span>
    <span class="number">{len(devices)}</span>
    <span class="card-detail">Celkem v inventáři</span>
  </div>
  <div class="card">
    <span class="card-label">Dostupné aktualizace</span>
    <span class="number">{total_updates}</span>
    <span class="card-detail">Napříč všemi systémy</span>
  </div>
  <div class="card">
    <span class="card-label">Vyžadují pozornost</span>
    <span class="number">{devices_with_updates}</span>
    <span class="card-detail">Zařízení s aktualizacemi</span>
  </div>
  <div class="card">
    <span class="card-label">Chyby kontroly</span>
    <span class="number">{device_errors}</span>
    <span class="card-detail">Zařízení s chybou načtení</span>
  </div>
</div>
<div class="toolbar">
  <div>
    <label for="system">Zobrazit systém: </label>
    <form method="get" action="" style="display:inline-block; margin-left: 6px;">
  <select id="system" name="system" onchange="this.form.submit()">
    <option value="all" {"selected" if system_filter == "all" else ""}>Všechna zařízení</option>
    <option value="debian" {"selected" if system_filter == "debian" else ""}>Debian</option>
    <option value="proxmox" {"selected" if system_filter == "proxmox" else ""}>Proxmox VE</option>
    <option value="openwrt" {"selected" if system_filter == "openwrt" else ""}>OpenWrt</option>
    <option value="homeassistant" {"selected" if system_filter == "homeassistant" else ""}>Home Assistant</option>
  </select>
</form>
  </div>
  <div style="display:flex; gap:8px; flex-wrap:wrap;">
    <form method="post" action="">
      <button type="submit">Zkontrolovat aktualizace</button>
    </form>
    <button type="button" onclick="document.getElementById('update-dialog').showModal()">Aktualizovat vybraná zařízení</button>
  </div>
</div>
<dialog id="update-dialog">
  <h2>Aktualizovat zařízení</h2>
  <p>Výběr vychází z aktuálního filtru dashboardu. Zařízení s vypnutou aktualizační politikou nebo nepodporovaným systémem nelze vybrat.</p>
  <form method="post" action="install?system={html.escape(system_filter, quote=True)}" onsubmit="return confirmUpdateSelection()">
    <div class="update-list">{update_modal}</div>
    <p id="selected-summary" class="muted"></p>
    <div class="modal-actions">
      <button type="button" class="secondary" onclick="document.getElementById('update-dialog').close()">Zrušit</button>
      <button type="submit">Potvrdit instalaci</button>
    </div>
  </form>
</dialog>
<script>
function confirmUpdateSelection() {{
  const selected = document.querySelectorAll('#update-dialog input[name="hosts"]:checked');
  if (!selected.length) {{
    alert('Vyber alespoň jedno podporované zařízení.');
    return false;
  }}
  const names = Array.from(selected).map(el => el.value);
  return confirm('Opravdu nainstalovat dostupné aktualizace na ' + names.length + ' zařízení?\\n\\n' + names.join(', ') + '\\n\\nZařízení se automaticky nerestartují.');
}}
function refreshSelectedSummary() {{
  const selected = document.querySelectorAll('#update-dialog input[name="hosts"]:checked').length;
  const summary = document.getElementById('selected-summary');
  if (summary) summary.textContent = 'Vybraná zařízení: ' + selected;
}}
document.querySelectorAll('#update-dialog input[name="hosts"]').forEach(el => el.addEventListener('change', refreshSelectedSummary));
refreshSelectedSummary();
</script>
<p class="muted">Zobrazeno {len(filtered_devices)} z {len(devices)} zařízení. Souhrnné statistiky výše zahrnují všechna zařízení.</p>
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
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        if parsed.path not in ("/", "/index.html"):
            self.send_error(404)
            return

        system_filter = parse_qs(parsed.query).get("system", ["all"])[0]
        allowed_filters = {"all", "debian", "proxmox", "openwrt", "homeassistant"}
        if system_filter not in allowed_filters:
            system_filter = "all"

        try:
            compatibility_notice = None
            try:
                data = api_request("/api/update-targets", timeout=15)
            except HTTPError as api_exc:
                # Older controller API versions expose /api/updates but not
                # /api/update-targets. Keep the dashboard useful while the
                # controller service is being updated.
                if api_exc.code != 404:
                    raise
                data = api_request("/api/updates", timeout=15)
                compatibility_notice = (
                    "API řadiče zatím nepodporuje /api/update-targets. "
                    "Zobrazuji dostupné výsledky z /api/updates; "
                    "pro správu vybraných aktualizací aktualizuj API na řadiči."
                )
            devices = data.get("devices", [])
            devices.extend(supervisor_devices())
            page = render_page(
                devices,
                error=compatibility_notice,
                system_filter=system_filter,
            )
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("Could not load updates: %s", type(exc).__name__)
            page = render_page(
                [],
                error="Nepodařilo se načíst data z API. Zkontroluj API a konfiguraci doplňku.",
            )

        self.send_html(page)

    def do_POST(self):
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        if parsed.path == "/install":
            system_filter = parse_qs(parsed.query).get("system", ["all"])[0]
            allowed_filters = {"all", "debian", "proxmox", "openwrt", "homeassistant"}
            if system_filter not in allowed_filters:
                system_filter = "all"
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 20000:
                    raise ValueError("Invalid form size")
                form = parse_qs(self.rfile.read(length).decode("utf-8"))
                hosts = form.get("hosts", [])
                if not hosts:
                    raise ValueError("Vyber alespoň jedno podporované zařízení.")
                result = api_request(
                    "/api/updates/install",
                    method="POST",
                    timeout=1800,
                    payload={"hosts": hosts},
                )
                data = api_request("/api/update-targets", timeout=15)
                devices = data.get("devices", [])
                devices.extend(supervisor_devices())
                notice = "Aktualizace dokončena pro: " + ", ".join(result.get("hosts", hosts))
                page = render_page(devices, notice=notice, system_filter=system_filter)
            except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                logger.warning("Selected package update failed: %s", type(exc).__name__)
                message = "Aktualizaci se nepodařilo dokončit. Ověř povolení zařízení a logy API."
                if isinstance(exc, HTTPError):
                    try:
                        detail = json.loads(exc.read().decode("utf-8")).get("detail")
                        if detail:
                            message = str(detail)
                    except (ValueError, OSError):
                        pass
                try:
                    data = api_request("/api/update-targets", timeout=15)
                    devices = data.get("devices", [])
                    devices.extend(supervisor_devices())
                except (HTTPError, URLError, TimeoutError, ValueError, OSError):
                    devices = []
                page = render_page(devices, error=message, system_filter=system_filter)
            self.send_html(page)
            return

        if parsed.path not in ("/", "/check"):
            self.send_error(404)
            return
        system_filter = parse_qs(parsed.query).get("system", ["all"])[0]
        allowed_filters = {"all", "debian", "proxmox", "openwrt", "homeassistant"}
        if system_filter not in allowed_filters:
            system_filter = "all"

        try:
            data = api_request(
                "/api/updates/check",
                method="POST",
                timeout=330,
            )
            target_data = api_request("/api/update-targets", timeout=15)
            devices = target_data.get("devices", [])
            devices.extend(supervisor_devices())
            total_updates = sum(int(device.get("update_count", 0)) for device in devices)
            notice = (
                "Kontrola dokončena. "
                f"Zobrazené položky: {len(devices)}, "
                f"dostupné aktualizace: {total_updates}."
            )
            page = render_page(devices, notice=notice, system_filter=system_filter)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("Update check failed: %s", type(exc).__name__)
            try:
                data = api_request("/api/update-targets", timeout=15)
                devices = data.get("devices", [])
                devices.extend(supervisor_devices())
            except (HTTPError, URLError, TimeoutError, ValueError, OSError):
                devices = []

            page = render_page(
                devices,
                error="Kontrola aktualizací selhala. Zkontroluj logy API a doplňku.",
                system_filter=system_filter,
            )

        self.send_html(page)

    def log_message(self, fmt, *args):
        logger.info("%s", fmt % args)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    server = ThreadingHTTPServer(("0.0.0.0", 8099), Handler)
    logger.info("Homelab Manager add-on listening on port 8099")
    server.serve_forever()
