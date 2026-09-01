#!/bin/bash

# @raycast.schemaVersion 1
# @raycast.title Compress iOS Scan
# @raycast.mode silent
# @raycast.icon 📉
# @raycast.description Compress selected iOS-scan PDF(s) (Notes/Files scanner output); saves alongside as *_compressed.pdf
# @raycast.author kovar
# @raycast.authorURL https://raycast.com/kovar
# @raycast.argument1 { "type": "dropdown", "placeholder": "Quality", "data": [{"title": "Small - 64 colors, 50% res (default, ~90% smaller)", "value": "small"}, {"title": "Lossless - no quality loss (~15-20% smaller)", "value": "lossless"}, {"title": "HQ - 256 colors, 100% res (~55-70% smaller)", "value": "hq"}, {"title": "Balanced - 64 colors, 75% res (~80% smaller)", "value": "balanced"}, {"title": "Tiny - 64 colors, 33% res (~96% smaller, aggressive)", "value": "tiny"}] }
# @raycast.argument2 { "type": "dropdown", "placeholder": "Page size (centimetres)", "data": [{"title": "Keep original page size", "value": "original"}, {"title": "A4 - 21.0 x 29.7 cm", "value": "a4"}, {"title": "A4 landscape - 29.7 x 21.0 cm", "value": "a4-landscape"}, {"title": "A5 - 14.8 x 21.0 cm", "value": "a5"}, {"title": "A5 landscape - 21.0 x 14.8 cm", "value": "a5-landscape"}, {"title": "A3 - 29.7 x 42.0 cm", "value": "a3"}, {"title": "A3 landscape - 42.0 x 29.7 cm", "value": "a3-landscape"}, {"title": "A6 - 10.5 x 14.8 cm", "value": "a6"}, {"title": "A6 landscape - 14.8 x 10.5 cm", "value": "a6-landscape"}, {"title": "A2 - 42.0 x 59.4 cm", "value": "a2"}, {"title": "A2 landscape - 59.4 x 42.0 cm", "value": "a2-landscape"}, {"title": "Custom - type centimetres below (W x H)", "value": "custom"}] }
# @raycast.argument3 { "type": "text", "placeholder": "Custom size in centimetres, e.g. 8.5x5.3", "optional": true }

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

quality="${1:-small}"
page_size="${2:-original}"
custom_size="$3"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

files=$(osascript -e '
tell application "Finder"
  set sel to selection
  set output to ""
  repeat with f in sel
    set output to output & POSIX path of (f as alias) & linefeed
  end repeat
  return output
end tell' 2>/dev/null)

if [ -z "$files" ]; then
  echo "No files selected in Finder"
  exit 1
fi

pdf_files=()
while IFS= read -r f; do
  [[ -n "$f" && ( "$f" == *.pdf || "$f" == *.PDF ) ]] && pdf_files+=("$f")
done <<< "$files"

if [ ${#pdf_files[@]} -lt 1 ]; then
  echo "Select at least 1 PDF file"
  exit 1
fi

args=(--quality "$quality")
case "$page_size" in
  original|"")
    ;;
  custom)
    if [ -z "$custom_size" ]; then
      echo "Custom size required: enter width x height in centimetres, e.g. 8.5x5.3"
      exit 1
    fi
    args+=(--size "$custom_size")
    ;;
  *)
    args+=(--size "$page_size")
    ;;
esac

uv run "$script_dir/compress-ios-scan.py" "${pdf_files[@]}" "${args[@]}"
