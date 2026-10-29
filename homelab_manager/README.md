# Homelab Manager

The read-only Home Assistant add-on displays devices from the Homelab Manager API.

## Configuration

- `api_url`: Base URL of the controller API, for example `http://192.168.0.186:18082`.
- `api_key`: API key created on the controller. Keep it private; do not commit it to Git.

The initial version lists devices and refreshes the page every 60 seconds. It does not install updates, reboot hosts, change Proxmox, or flash OpenWrt.

## Building

Images are published to GitHub Container Registry by the workflow in `.github/workflows/publish-addon.yml`.

To publish a new release, update the `version` field in `config.yaml` and push the change to `main`.