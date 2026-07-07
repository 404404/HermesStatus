#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

if [ "${HERMES_EXPORT_ENABLED:-true}" = "true" ] && [ -x /app/export-hermes-status.py ]; then
  (
    while :; do
      python3 /app/export-hermes-status.py >/tmp/hermes-export.log 2>&1 || true
      sleep "${HERMES_EXPORT_INTERVAL:-600}"
    done
  ) &
fi

case "${CLIENT:-linux}" in
  linux|client-linux|client-linux.py)
    exec python3 /app/client-linux.py
    ;;
  psutil|client-psutil|client-psutil.py)
    exec python3 /app/client-psutil.py
    ;;
  *)
    echo "Unknown CLIENT='$CLIENT'. Use 'linux' or 'psutil'." >&2
    exit 2
    ;;
esac
