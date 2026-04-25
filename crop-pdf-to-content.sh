#!/bin/bash

export PATH="$HOME/.local/bin:$PATH"

# @raycast.schemaVersion 1
# @raycast.title Crop PDF
# @raycast.mode silent
# @raycast.icon 📄
# @raycast.description Crop selected PDF to content
# @raycast.author kovar
# @raycast.authorURL https://raycast.com/kovar

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
  output="${file%.*}_cropped.pdf"
  uv tool run pdfcropmargins -p 3 "$file" -o "$output"
done <<< "$files"
