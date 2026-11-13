#!/bin/sh
set -eu

: "${SCANNER_IP:?set SCANNER_IP}"

set -- \
  --scanner-ip "$SCANNER_IP" \
  --output-dir "${OUTPUT_DIR:-/data/scans}" \
  --dpi "${DPI:-300}" \
  --format "${FORMAT:-pdf}" \
  --mode "${MODE:-Color}" \
  --paper-size "${PAPER_SIZE:-A4}" \
  --source "${SOURCE:-ADF Front}" \
  --idle-timeout "${IDLE_TIMEOUT:-10}" \
  --reconnect-interval "${RECONNECT_INTERVAL:-3}" \
  --scan-timeout "${SCAN_TIMEOUT:-120}" \
  "$@"

case "${VERBOSE:-false}" in
  1|true|TRUE|yes|YES|on|ON)
    set -- --verbose "$@"
    ;;
esac

exec python -m papertrailscan.button_scan "$@"
