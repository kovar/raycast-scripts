#!/bin/bash

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

# @raycast.schemaVersion 1
# @raycast.title Merge PDFs
# @raycast.mode silent
# @raycast.icon 🔀
# @raycast.description Merge selected PDFs into one file (saved next to first selected file)
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

pdf_files=()
while IFS= read -r f; do
  [[ -n "$f" && ( "$f" == *.pdf || "$f" == *.PDF ) ]] && pdf_files+=("$f")
done <<< "$files"

if [ ${#pdf_files[@]} -lt 2 ]; then
  echo "Select at least 2 PDF files"
  exit 1
fi

dir=$(dirname "${pdf_files[0]}")
output="$dir/merged.pdf"
counter=1
while [ -e "$output" ]; do
  output="$dir/merged_$counter.pdf"
  (( counter++ ))
done

pdfunite "${pdf_files[@]}" "$output"
