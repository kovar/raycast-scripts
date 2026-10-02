#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Start Grafana Export Session
# @raycast.mode silent
# @raycast.packageName Grafana
# @raycast.icon 🖨️

# Dependencies:
#   uv:      curl -LsSf https://astral.sh/uv/install.sh | sh
#   poppler: brew install poppler   (provides pdftoppm for PDF→PNG conversion)

PID_FILE="$HOME/.grafana-png-exporter/session.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  osascript -e 'display notification "A session is already running" with title "Grafana Exporter"'
  exit 0
fi

UV="$(command -v uv)"
for candidate in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
  [ -n "$UV" ] && break
  [ -x "$candidate" ] && UV="$candidate"
done
if [ -z "$UV" ]; then
  osascript -e 'display notification "uv not found - install it first" with title "Grafana Exporter"'
  exit 1
fi

mkdir -p "$HOME/.grafana-png-exporter"
nohup "$UV" run ~/raycast/scripts/grafana-png-export.py \
  > "$HOME/.grafana-png-exporter/session.log" 2>&1 &
