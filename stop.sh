#!/usr/bin/env bash
# Stop the Seller Desk server started by start.sh (only the Python process listening on port 8000)
pids=$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null)
stopped=0
for pid in $pids; do
  if ps -p "$pid" -o comm= | grep -qi python; then
    kill "$pid" && stopped=1 && echo "Stopped Seller Desk (process $pid)."
  fi
done
[ "$stopped" = 1 ] || echo "Seller Desk is not running."
