#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Stop Grafana Export Session
# @raycast.mode silent
# @raycast.packageName Grafana
# @raycast.icon ⏹️

PID_FILE="$HOME/.grafana-png-exporter/session.pid"

if [ ! -f "$PID_FILE" ] || ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  osascript -e 'display notification "No active session" with title "Grafana Exporter"'
  exit 0
fi

kill "$(cat "$PID_FILE")"
