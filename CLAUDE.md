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
2. Fit the browser window so the page area is exactly the session's format (default 1920×1080 CSS px) —
   at session start and again at each export (undoes manual resizes). Then raise the pixel
   ratio to `--dpr` (default 4) via `setDeviceMetricsOverride` at the same size, only for
   the duration of the export (no re-layout, just sharper canvases)
3. Enter kiosk mode (`kiosk` + `hideLogo` URL params) **without reloading** (see below)
4. Inject CSS (`<style id=EXPORT_STYLE_ID>`): hide refresh picker, dashboard tab bar, panel "⋮"
   menu, panel resize handles (`.scene-resize-handle`), the "Add variable" (+) button
   (`.dashboard-canvas-add-button`; its row too when it holds nothing else, so variables stay);
   fix print-mode time picker. **The style element is removed after the export** — with the
   in-place kiosk there is no reload, so it would otherwise stay in the user's live view.
5. `Page.printToPDF` (CDP) on a single page as tall as the content → PDF file
6. `pdftoppm -r 300 -png -singlefile -x 0 -y 0 -W <w> -H <h>` crops the visible frame → PNG
   (e.g. 6000×3375 for 16:9; `PNG_DPI` = 300, so 1 CSS px = 3.125 PNG px in every format)
7. PNG copied to clipboard (image; on Windows also as a file) unless `--no-clipboard`
8. Browser returns to the original URL and view, viewport override cleared — even on failure

**In-place kiosk (keeps unsaved view state)**: series hidden by clicking the legend, and similar
temporary state, live only in the page and are lost on reload. So kiosk is entered via
`history.pushState` + a synthetic `popstate` (Grafana's router picks it up, no reload), and left
via `history.back()` + an **Esc** keypress — Grafana does not leave kiosk when the URL param
disappears, only on Esc. Kiosk is detected by `<header>` count dropping to 0 (verified on 13.1).
If that can't be confirmed, it falls back to a full reload (old behavior; view state lost); if the
exit leaves a different URL or no header, the original URL is reloaded.

Output name: `{dashboard title}_{YYYYmmdd_HHMMSS}.png` (title from `document.title`).
The intermediate PDF lives in a temp dir, never in the output dir.
Before printing, the export waits (up to 30s) for panel loading bars
(`[aria-label="Panel loading bar"]`) to disappear, on top of the fixed 5s post-navigation wait.

**Export formats** (`--format`, chosen in the Start Session dropdown; fixed for the session):
`EXPORT_FORMATS` presets — `16:9` 1920×1080 (default), `16:10` 1920×1200, `4:3` 1600×1200,
`a4-landscape` 1697×1200, `a4` 849×1200 — or a custom `WIDTHxHEIGHT` in CSS px (`parse_format`).
Preset heights stay <= 1200 so the window fits a 1440p screen with browser chrome. A4 portrait is
849 px wide, just above Grafana's ~769 px single-column breakpoint. Raycast dropdown titles in
the PS1 wrapper use plain ASCII (`x`, `-`), per the PowerShell gotchas below.

**What you see is what you export**: every export is exactly the frame the user sees
(minus Grafana's header, which kiosk hides), at a fixed size per format. Content below the fold is
cut, as on screen. The export captures from the top of the dashboard, even if the user scrolled.
- If the screen can't fit the page area (e.g. a 125%-scaled laptop screen), a warning is
  logged/notified; the export still renders at the format's size but won't match the window.
- Don't clamp the window position via `screen.avail*`: Brave's fingerprinting protection reports
  fake screen dimensions (2560×1440 at 0,0 on a 3440×1440 secondary monitor).

**Why the tall PDF page + crop**: a viewport-sized PDF page prints charts blank — Chrome won't split
a canvas across a page break, so a chart crossing the bottom edge moves wholly to page 2.
`_CONTENT_HEIGHT_JS` measures the content (Grafana 13+ scrolls an inner container, so
`document.scrollHeight` alone misses it); capped at `MAX_PAPER_HEIGHT`. Panels fully below the
fold are never rendered (lazy-loaded) — irrelevant, they're cropped away.

**CRITICAL**: Must use `Page.printToPDF` → `pdftoppm`, NOT `Page.captureScreenshot`.
`captureScreenshot` shows black/blank canvas for GPU-composited uplot charts.

### IPC
- **macOS**: UNIX signals — SIGUSR1 = export, SIGTERM = stop
- **Windows**: Polling trigger files every 0.5s — `export.trigger`, `stop.trigger`
- Both share one run loop (`_run_loop`) with the same export handling and keep-alive.
- `session.pid` is written at the very start of `main()` (before the browser launches),
  so Raycast commands see the session immediately.

### Data Directory
`~/.grafana-png-exporter/`
- `session.pid` — PID of running Python process
- `export.trigger` / `stop.trigger` — Windows IPC files
- `session.log` — Python stdout/stderr (line-buffered, so it updates live)
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
**Update (Grafana 13.1, 2026-10):** with the viewport override applied per export instead of
once at session start, live exports on Windows come out at 6000px wide. The old session-wide
override was observed to be inactive on a long-running session (page at real window size,
DPR 1.25 from Windows display scaling), which is a likely root cause.
Windows output is ~3000×1687 instead of macOS 6000×3375. Root cause unknown
(likely display scaling affecting CSS viewport). Accepted as-is — 3000px is sufficient.
**Do not attempt to fix** — multiple approaches failed:
- `--force-device-scale-factor=1` flag
- `setDeviceMetricsOverride` scale adjustment
- `pdftoppm -scale-to-x 6000`

### Session Stability
Windows ChromeDriver has idle session timeout (~60s). Fixed with (now on all platforms):
- Keep-alive `driver.execute_script("return 1")` every 15s in run loop
- Dead driver detection: 3 consecutive keep-alive failures → clean exit
  (also ends the session when the user closes the browser window)
- Chrome flags: `--disable-background-timer-throttling`, `--disable-renderer-backgrounding`,
  `--disable-backgrounding-occluded-windows`

### Windows Background Process Launch
`-WindowStyle Hidden` + `-RedirectStandardOutput` are incompatible in PowerShell.
Fixed via generated `launcher.ps1` that handles its own I/O redirection:
```powershell
Start-Process powershell -WindowStyle Hidden `
  -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher
```

### Timezone Override
Chrome CDP `Emulation.setTimezoneOverride` requires IANA IDs (e.g. "Europe/Berlin").
`tzlocal.get_localzone_name()` provides them on all platforms (it maps Windows zone
names internally). If lookup or the override fails, the override is skipped.

### Platform Detection
`platform.system()` returns `"Darwin"` (capital D) on macOS — compare against the
module-level `SYSTEM` constant, never `"darwin"`. (A lowercase comparison previously
silently disabled all macOS notifications.)

### Notifications & Clipboard
Messages/paths are passed to `osascript`/PowerShell as argv or env vars
(`GPE_MESSAGE`, `GPE_PNG`), never interpolated into script source — error messages
contain quotes, `$` and newlines. Notifications are fire-and-forget (`Popen`).

### Encoding & Buffering
`sys.stdout.reconfigure(..., line_buffering=True)` at script top — line buffering so
`session.log` is written live; on Windows also `encoding="utf-8", errors="replace"`
because the cp1252 default can't encode emoji in log output.

### @media print CSS Fix
Grafana's CSS-in-JS hides the time picker label in print mode. Fixed by injecting:
```css
@media print {
  [data-testid="data-testid TimePicker Open Button"] > div { display: block !important; }
}
```

### "Powered by Grafana" Ribbon (Grafana 12.4+)
Kiosk mode shows a "Powered by Grafana" ribbon at the bottom that can cover panels.
The export URL gets `hideLogo` alongside `kiosk` (`EXPORT_URL_PARAMS`); the page is
reloaded whenever either param is missing. Known gap: Grafana ignores `hideLogo` on
playlist pages (grafana/grafana#119341).

### Dashboard Tabs (grouped dashboards)
The tab bar of dashboards using tabs layout (seen on Grafana 13.1) is hidden by injected CSS:
`div:has(> [role="tablist"] [data-tab-activation-key])` — the wrapper carries the underline;
`data-tab-activation-key` is specific to dashboard tabs. The rule is not inside `@media print`
so `scrollHeight` excludes the bar. The active tab survives the kiosk reload via the `dtab` URL param.

### Stale Trigger Files
At the very start of `main()`, stale `export.trigger` and `stop.trigger` are deleted to prevent
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
