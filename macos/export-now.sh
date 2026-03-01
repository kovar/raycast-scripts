#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Export Grafana PNG Now
# @raycast.mode silent
# @raycast.packageName Grafana
# @raycast.icon 📄

PID_FILE="$HOME/.grafana-png-exporter/session.pid"

if [ ! -f "$PID_FILE" ] || ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  osascript -e 'display notification "No active session — run \"Start Grafana Export Session\" first" with title "Grafana Exporter"'
  exit 1
fi

kill -SIGUSR1 "$(cat "$PID_FILE")"
