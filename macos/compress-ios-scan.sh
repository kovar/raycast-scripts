#!/bin/bash

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

# @raycast.schemaVersion 1
# @raycast.title Compress iOS Scan
# @raycast.mode silent
# @raycast.icon 📉
# @raycast.description Compress selected iOS-scan PDF(s) (Notes/Files scanner output); saves alongside as *_compressed.pdf
# @raycast.author kovar
# @raycast.authorURL https://raycast.com/kovar
# @raycast.argument1 { "type": "dropdown", "placeholder": "Quality", "data": [
#   { "title": "Small - 64 colors, 50% res (default, ~90% smaller)", "value": "small" },
#   { "title": "Lossless - no quality loss (~15-20% smaller)", "value": "lossless" },
#   { "title": "HQ - 256 colors, 100% res (~55-70% smaller)", "value": "hq" },
#   { "title": "Balanced - 64 colors, 75% res (~80% smaller)", "value": "balanced" },
#   { "title": "Tiny - 64 colors, 33% res (~96% smaller, aggressive)", "value": "tiny" }
# ] }
# @raycast.argument2 { "type": "text", "placeholder": "Real size in cm, e.g. 8.5x5.3 (optional, recommended for lossy tiers)", "optional": true }

quality="${1:-small}"
size="$2"

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
[ -n "$size" ] && args+=(--size "$size")

uv run "$script_dir/compress-ios-scan.py" "${pdf_files[@]}" "${args[@]}"
