#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

case "${HERMES_EXPORT_ENABLED:-true}" in
  1|true|TRUE|yes|YES|on|ON)
    (
      while :; do
        python3 /app/export-hermes-status.py || true
        sleep "${HERMES_EXPORT_INTERVAL:-600}"
      done
    ) &
    ;;
esac

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
