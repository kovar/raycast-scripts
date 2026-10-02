#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Start Grafana Export Session
# @raycast.mode silent
# @raycast.packageName Grafana
# @raycast.icon 🖨️
# @raycast.argument1 { "type": "dropdown", "placeholder": "Export format", "data": [{"title": "16:9 - 1920 x 1080 page, 6000 x 3375 PNG (default)", "value": "16:9"}, {"title": "A4 landscape - 1697 x 1200 page, 5303 x 3750 PNG", "value": "a4-landscape"}, {"title": "A4 portrait - 849 x 1200 page, 2653 x 3750 PNG", "value": "a4"}, {"title": "16:10 - 1920 x 1200 page, 6000 x 3750 PNG", "value": "16:10"}, {"title": "4:3 - 1600 x 1200 page, 5000 x 3750 PNG", "value": "4:3"}, {"title": "Custom - type page size in px below (W x H)", "value": "custom"}] }
# @raycast.argument2 { "type": "text", "placeholder": "Custom page size in px, e.g. 1400x990", "optional": true }

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

format="${1:-16:9}"
if [ "$format" = "custom" ]; then
  format="$(echo "$2" | tr -d ' ')"
  if ! [[ "$format" =~ ^[0-9]+[xX][0-9]+$ ]]; then
    osascript -e 'display notification "Custom size required - enter page size in px, e.g. 1400x990" with title "Grafana Exporter"'
    exit 1
  fi
fi

mkdir -p "$HOME/.grafana-png-exporter"
nohup "$UV" run ~/raycast/scripts/grafana-png-export.py --format "$format" \
  > "$HOME/.grafana-png-exporter/session.log" 2>&1 &
