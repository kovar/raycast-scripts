#!/bin/bash

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

# @raycast.schemaVersion 1
# @raycast.title Extract PDF Pages
# @raycast.mode silent
# @raycast.icon ✂️
# @raycast.description Extract a page or range from selected PDF and save as new file
# @raycast.author kovar
# @raycast.authorURL https://raycast.com/kovar
# @raycast.argument1 {"type": "text", "placeholder": "Page or range (e.g. 3 or 2-5)"}

range="$1"

if [[ ! "$range" =~ ^[0-9]+(-[0-9]+)?$ ]]; then
  echo "Invalid range: use a number or x-y format"
  exit 1
fi

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

while IFS= read -r file; do
  [[ -z "$file" || ( "$file" != *.pdf && "$file" != *.PDF ) ]] && continue

  total=$(qpdf --show-npages "$file" 2>/dev/null)
  if [[ ! "$total" =~ ^[0-9]+$ ]]; then
    echo "Could not read $(basename "$file")"
    continue
  fi

  if [[ "$range" =~ ^([0-9]+)-([0-9]+)$ ]]; then
    start="${BASH_REMATCH[1]}"; end="${BASH_REMATCH[2]}"
  else
    start="$range"; end="$range"
  fi

  if [ "$start" -lt 1 ] || [ "$end" -gt "$total" ] || [ "$start" -gt "$end" ]; then
    echo "Range $range out of bounds (file has $total pages)"
    continue
  fi

  dir=$(dirname "$file")
  base=$(basename "${file%.*}")
  output="$dir/${base}_p${range}.pdf"
  counter=1
  while [ -e "$output" ]; do
    output="$dir/${base}_p${range}_${counter}.pdf"
    (( counter++ ))
  done

  qpdf "$file" --pages "$file" "$range" -- "$output"
done <<< "$files"
