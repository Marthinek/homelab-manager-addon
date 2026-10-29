#!/usr/bin/with-contenv bashio
set -e

export HOMELAB_API_URL="$(bashio::config 'api_url')"
export HOMELAB_API_KEY="$(bashio::config 'api_key')"

exec python3 /app.py
