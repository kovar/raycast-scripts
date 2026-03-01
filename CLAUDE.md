# Raycast Scripts — Grafana PNG Exporter

## Project Overview
Grafana dashboard → high-quality PNG exporter for Raycast (macOS + Windows).
Three Raycast commands per platform: Start Session, Export Now, Stop Session.

## File Structure
```
~/raycast/scripts/
  grafana-png-export.py      # Shared Python script (both platforms)
  macos/
    start-session.sh
    export-now.sh
    stop-session.sh
  windows/
    start-session.ps1
    export-now.ps1
    stop-session.ps1
```

## Key Architecture

### Export Pipeline
1. Selenium WebDriver controls Brave (macOS/Windows) or Chrome
2. Navigate to Grafana dashboard with `?kiosk` suffix
3. Inject CSS to fix print-mode rendering issues
4. `Page.printToPDF` (CDP) → PDF file
5. `pdftoppm -r 300 -png -singlefile` → PNG (~6000×3375 on macOS, ~3000px on Windows)

**CRITICAL**: Must use `Page.printToPDF` → `pdftoppm`, NOT `Page.captureScreenshot`.
`captureScreenshot` shows black/blank canvas for GPU-composited uplot charts.

### IPC
- **macOS**: UNIX signals — SIGUSR1 = export, SIGTERM = stop
- **Windows**: Polling trigger files every 0.5s — `export.trigger`, `stop.trigger`

### Data Directory
`~/.grafana-png-exporter/`
- `session.pid` — PID of running Python process
- `export.trigger` / `stop.trigger` — Windows IPC files
- `session.log` — Python stdout/stderr (Windows only)
- `launcher.ps1` — generated launcher script (Windows)
- `{browser}-profile/` — automation browser profile

### Browser Profiles
Separate profile at `~/.grafana-png-exporter/{browser}-profile/` to avoid conflicts
with user's regular browser instance.

### Dependencies
- **macOS**: `uv` (runs Python script), `brew install poppler` (pdftoppm)
- **Windows**: `uv`, `winget install oschwartz10612.Poppler`
  - Poppler installs to `%LOCALAPPDATA%\Programs\poppler-*\Library\bin\` (not on PATH)
  - Code globs for it in `_find_pdftoppm()`

## Known Issues & Decisions

### Windows Resolution (3000px wide, accepted)
Windows output is ~3000×1687 instead of macOS 6000×3375. Root cause unknown
(likely display scaling affecting CSS viewport). Accepted as-is — 3000px is sufficient.
**Do not attempt to fix** — multiple approaches failed:
- `--force-device-scale-factor=1` flag
- `setDeviceMetricsOverride` scale adjustment
- `pdftoppm -scale-to-x 6000`

### Windows Session Stability
Windows ChromeDriver has idle session timeout (~60s). Fixed with:
- Keep-alive `driver.execute_script("return 1")` every 15s in run loop
- Dead driver detection: 3 consecutive keep-alive failures → clean exit
- Chrome flags: `--disable-background-timer-throttling`, `--disable-renderer-backgrounding`,
  `--disable-backgrounding-occluded-windows`

### Windows Background Process Launch
`-WindowStyle Hidden` + `-RedirectStandardOutput` are incompatible in PowerShell.
Fixed via generated `launcher.ps1` that handles its own I/O redirection:
```powershell
Start-Process powershell -WindowStyle Hidden `
  -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher
```

### Windows Timezone → IANA Mapping
`tzutil /g` returns Windows names (e.g. "Central Europe Standard Time").
Chrome CDP `Emulation.setTimezoneOverride` requires IANA IDs (e.g. "Europe/Budapest").
`_WINDOWS_TO_IANA` dict in script handles conversion; unknown zones are skipped.

### Windows Encoding
`sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at script top —
Windows cp1252 default can't encode emoji in log output.

### @media print CSS Fix
Grafana's CSS-in-JS hides the time picker label in print mode. Fixed by injecting:
```css
@media print {
  [data-testid="data-testid TimePicker Open Button"] > div { display: block !important; }
}
```

### Stale Trigger Files
On session start, stale `export.trigger` and `stop.trigger` are deleted to prevent
a leftover `stop.trigger` from immediately killing a fresh session.

### Windows Fast Shutdown
After `driver.quit()`, force-kill remaining chromedriver tree:
```python
subprocess.run(["taskkill", "/F", "/T", "/PID", str(chromedriver_pid)], capture_output=True)
```

## Platform Defaults
- macOS: Brave browser
- Windows: Brave browser (path: `C:\Program Files\BraveSoftware\...` or `%LOCALAPPDATA%\BraveSoftware\...`)

## PowerShell Gotchas
- Em-dash `—` in PS1 strings causes parse errors (UTF-8 byte 0x94 = closing `"` in cp1252)
- Use plain hyphens `-` in all PowerShell string literals
