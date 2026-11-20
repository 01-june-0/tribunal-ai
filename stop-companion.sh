#!/usr/bin/env sh
# Stops the companion started by start-companion.sh. Only the recorded PID is stopped, and only if it is still
# companion_server.py; records, worktrees and mission state stay on disk.
cd "$(dirname "$0")"
if [ ! -f data/companion.pid ]; then
  echo "no data/companion.pid; nothing to stop"
  exit 0
fi
PID="$(cat data/companion.pid)"
if ps -p "$PID" -o command= 2>/dev/null | grep -q companion_server.py; then
  kill "$PID"
  # Wait until the process is gone, so an immediate start-companion.sh finds the port free.
  i=0
  while kill -0 "$PID" 2>/dev/null && [ "$i" -lt 20 ]; do i=$((i + 1)); sleep 0.5; done
  rm -f data/companion.pid
  echo "Tribunal AI companion stopped; records and worktrees preserved."
else
  rm -f data/companion.pid
  echo "PID $PID is not companion_server.py (already stopped?); pid file removed."
fi
