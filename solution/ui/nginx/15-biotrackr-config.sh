#!/bin/sh
# Copyright (c) 2026 Will Velida
# SPDX-License-Identifier: MIT
#
# 15-biotrackr-config.sh
# Validates the chat-ui runtime settings and writes /config.json before nginx
# starts. Runs from /docker-entrypoint.d/, ahead of the image's envsubst step
# (20-envsubst-on-templates.sh). Any invalid value stops the container.
#
## Required Environment Variables:
# TENANT_ID         - Entra tenant id (GUID)
# SPA_APP_ID        - biotrackr-demo-spa app id (GUID)
# BLUEPRINT_APP_ID  - Agent ID Blueprint app id (GUID)
# CHAT_API_URL      - chat-api origin, https://host[:port] with no path

set -eu

readonly CONFIG_DIR="/tmp/biotrackr"
# 8-4-4-4-12 hex digits.
readonly GUID_RE='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
# An https origin only: no path, query, fragment, or credentials.
readonly ORIGIN_RE='^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$'

err() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_match() {
  name="$1"
  value="$2"
  pattern="$3"
  if ! printf '%s' "${value}" | grep -Eq "${pattern}"; then
    err "${name} is missing or invalid"
  fi
}

main() {
  require_match TENANT_ID "${TENANT_ID:-}" "${GUID_RE}"
  require_match SPA_APP_ID "${SPA_APP_ID:-}" "${GUID_RE}"
  require_match BLUEPRINT_APP_ID "${BLUEPRINT_APP_ID:-}" "${GUID_RE}"
  require_match CHAT_API_URL "${CHAT_API_URL:-}" "${ORIGIN_RE}"

  mkdir -p "${CONFIG_DIR}"
  # Values are validated above, so they cannot break out of the JSON strings.
  printf '{"tenantId":"%s","spaAppId":"%s","blueprintAppId":"%s","chatApiUrl":"%s"}\n' \
    "${TENANT_ID}" "${SPA_APP_ID}" "${BLUEPRINT_APP_ID}" "${CHAT_API_URL}" \
    > "${CONFIG_DIR}/config.json"
}

main "$@"
