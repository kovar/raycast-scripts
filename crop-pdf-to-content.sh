#!/bin/bash

export PATH="$HOME/.local/bin:$PATH"

# @raycast.schemaVersion 1
# @raycast.title Crop PDF
# @raycast.mode silent
# @raycast.icon 📄
# @raycast.description Crop selected PDF to content
# @raycast.author kovar
# @raycast.authorURL https://raycast.com/kovar

file=$(osascript -e 'tell application "Finder" to POSIX path of (selection as alias)' 2>/dev/null)
output="${file%.*}_cropped.pdf"

uv tool run pdfcropmargins -p 3 "$file" -o "$output"
