#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "selenium>=4.20",
#   "tzlocal>=5.0",
# ]
# ///

import sys
import time
import os
import re
import base64
import platform
import argparse
import shutil
import signal
import subprocess
import tempfile
import threading
import glob
from urllib.parse import urlsplit, urlunsplit, parse_qs, unquote

# Line buffering so session.log updates live (stdout is redirected to a file by the launchers).
# On Windows also force UTF-8 — the cp1252 default can't encode emoji in log output.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
else:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

SYSTEM = platform.system()  # "Darwin" | "Windows" | "Linux"
DATA_DIR = os.path.expanduser("~/.grafana-png-exporter")
PID_FILE = os.path.join(DATA_DIR, "session.pid")
EXPORT_TRIGGER = os.path.join(DATA_DIR, "export.trigger")
STOP_TRIGGER = os.path.join(DATA_DIR, "stop.trigger")

KEEPALIVE_INTERVAL = 15  # seconds
KEEPALIVE_MAX_FAILURES = 3
PANEL_LOADING_SELECTOR = '[aria-label="Panel loading bar"], .panel-loading'
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if SYSTEM == "Windows" else 0

# Export formats: page area in CSS px. The browser window is sized so the page area is
# exactly this, and the export captures exactly this frame (what you see is what you
# export). Heights stay <= 1200 so the window fits a 1440p screen including browser chrome.
EXPORT_FORMATS = {
    "16:9": (1920, 1080),
    "16:10": (1920, 1200),
    "4:3": (1600, 1200),
    "a4-landscape": (1697, 1200),  # 1:sqrt(2)
    "a4": (849, 1200),
}
DEFAULT_FORMAT = "16:9"
EXPORT_VIEWPORT = EXPORT_FORMATS[DEFAULT_FORMAT]
PNG_DPI = 300  # same scale for every format: 1920×1080 CSS px → 6000×3375 PNG


def parse_format(value: str) -> tuple[int, int]:
    """A preset name from EXPORT_FORMATS, or a custom 'WIDTHxHEIGHT' in CSS px."""
    key = value.strip().lower()
    if key in EXPORT_FORMATS:
        return EXPORT_FORMATS[key]
    m = re.fullmatch(r"(\d+)\s*[x×]\s*(\d+)", key)
    if m:
        width, height = int(m[1]), int(m[2])
        if 320 <= width <= 7680 and 240 <= height <= 4320:
            return width, height
    raise argparse.ArgumentTypeError(
        f"invalid format '{value}': use one of {', '.join(EXPORT_FORMATS)} or WIDTHxHEIGHT (e.g. 1400x990)")


def platform_default_browser():
    return "brave" if SYSTEM in ("Darwin", "Windows") else "chrome"


def get_browser_config(browser_name: str):
    automation_profile = os.path.join(DATA_DIR, f"{browser_name}-profile")
    os.makedirs(automation_profile, exist_ok=True)

    if browser_name == "brave":
        if SYSTEM == "Darwin":
            binary = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
        else:
            candidates = [
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            ]
            binary = next((p for p in candidates if os.path.exists(p)), candidates[0])
            print(f"✅ Brave binary: {binary}")
        return binary, automation_profile

    elif browser_name == "edge":
        binary = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" if SYSTEM == "Darwin" \
            else r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        return binary, automation_profile

    else:  # chrome
        return None, automation_profile


def get_system_timezone() -> str | None:
    """Return the local IANA timezone ID (e.g. 'Europe/Berlin'), or None if unavailable."""
    try:
        from tzlocal import get_localzone_name
        return get_localzone_name()
    except Exception as e:
        print(f"⚠️  Could not determine system timezone ({e}), skipping timezone override")
        return None


def apply_session_settings(driver):
    """Session-wide settings (per CDP connection)."""
    tz = get_system_timezone()
    if tz:
        try:
            driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": tz})
            print(f"✅ Timezone: {tz}")
        except Exception as e:
            print(f"⚠️  Timezone override '{tz}' rejected: {e}")


def create_driver(browser_name: str, user_data_dir: str = None, viewport=EXPORT_VIEWPORT):
    binary, automation_profile = get_browser_config(browser_name)
    profile_dir = user_data_dir or automation_profile

    opts = Options()
    if binary:
        opts.binary_location = binary
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-background-timer-throttling")
    opts.add_argument("--disable-renderer-backgrounding")
    opts.add_argument("--disable-backgrounding-occluded-windows")

    driver = webdriver.Chrome(options=opts)
    print(f"✅ Launched {browser_name.capitalize()} (automation profile: {profile_dir})")
    apply_session_settings(driver)
    fit_window_to_viewport(driver, viewport)
    return driver


def notify(message: str):
    """Show a desktop notification without blocking. The message is passed as an
    argument / env var, never interpolated into script source, so quotes are safe."""
    message = " ".join(str(message).split())[:200]
    try:
        if SYSTEM == "Darwin":
            subprocess.Popen(
                ["osascript",
                 "-e", "on run argv",
                 "-e", 'display notification (item 1 of argv) with title "Grafana Exporter"',
                 "-e", "end run",
                 message],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif SYSTEM == "Windows":
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command",
                 'Add-Type -AssemblyName System.Windows.Forms; '
                 '$n = New-Object System.Windows.Forms.NotifyIcon; '
                 '$n.Icon = [System.Drawing.SystemIcons]::Information; '
                 '$n.Visible = $true; '
                 '$n.ShowBalloonTip(5000, "Grafana Exporter", $env:GPE_MESSAGE, 1); '
                 'Start-Sleep -Milliseconds 500; $n.Dispose()'],
                env={**os.environ, "GPE_MESSAGE": message},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
    except Exception as e:
        print(f"⚠️  Notification failed: {e}")


def copy_png_to_clipboard(png_path: str) -> bool:
    """Put the PNG on the clipboard as an image (Windows: also as a file, for pasting into Explorer/Slack)."""
    try:
        if SYSTEM == "Darwin":
            result = subprocess.run(
                ["osascript",
                 "-e", "on run argv",
                 "-e", "set the clipboard to (read (POSIX file (item 1 of argv)) as «class PNGf»)",
                 "-e", "end run",
                 png_path],
                capture_output=True, timeout=30,
            )
        elif SYSTEM == "Windows":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command",
                 'Add-Type -AssemblyName System.Windows.Forms, System.Drawing; '
                 '$img = [System.Drawing.Image]::FromFile($env:GPE_PNG); '
                 '$data = New-Object System.Windows.Forms.DataObject; '
                 '$data.SetImage($img); '
                 '$files = New-Object System.Collections.Specialized.StringCollection; '
                 '[void]$files.Add($env:GPE_PNG); '
                 '$data.SetFileDropList($files); '
                 '[System.Windows.Forms.Clipboard]::SetDataObject($data, $true); '
                 '$img.Dispose()'],
                env={**os.environ, "GPE_PNG": png_path},
                capture_output=True, timeout=30, creationflags=_NO_WINDOW,
            )
        else:
            return False
    except Exception as e:
        print(f"⚠️  Clipboard copy failed: {e}")
        return False
    if result.returncode != 0:
        print(f"⚠️  Clipboard copy failed: {result.stderr.decode(errors='replace').strip()}")
        return False
    return True


def _find_pdftoppm() -> str:
    p = shutil.which("pdftoppm")
    if p:
        return p
    candidates = [
        "/opt/homebrew/bin/pdftoppm",
        "/usr/local/bin/pdftoppm",
        "/usr/bin/pdftoppm",
        r"C:\Program Files\poppler\Library\bin\pdftoppm.exe",
    ]
    for pattern in [
        r"C:\Program Files\poppler-*\Library\bin\pdftoppm.exe",
        r"C:\ProgramData\scoop\apps\poppler\*\bin\pdftoppm.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\poppler-*\Library\bin\pdftoppm.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\oschwartz10612.Poppler_*\poppler-*\Library\bin\pdftoppm.exe"),
    ]:
        candidates.extend(glob.glob(pattern))
    for c in candidates:
        if os.path.isfile(c):
            return c
    if SYSTEM == "Windows":
        raise RuntimeError("pdftoppm not found. Install poppler: winget install oschwartz10612.Poppler")
    raise RuntimeError("pdftoppm not found. Install poppler: brew install poppler")


def fit_window_to_viewport(driver, viewport=EXPORT_VIEWPORT) -> bool:
    """Resize the browser window so the page area (innerWidth x innerHeight) matches
    `viewport`. Window sizes are in device-independent px, so display scaling
    (e.g. Windows 125%) is handled; window borders/toolbars are measured, not guessed."""
    width, height = viewport

    def fits(inner_w, inner_h):  # fractional display scaling can leave a px or two off
        return abs(inner_w - width) <= 2 and abs(inner_h - height) <= 2

    for _ in range(4):
        inner_w, inner_h = driver.execute_script("return [innerWidth, innerHeight]")
        if fits(inner_w, inner_h):
            return True
        size = driver.get_window_size()
        driver.set_window_size(size["width"] + width - inner_w, size["height"] + height - inner_h)
        time.sleep(0.3)
    inner_w, inner_h = driver.execute_script("return [innerWidth, innerHeight]")
    if fits(inner_w, inner_h):
        return True
    print(f"⚠️  Could not size the page area to {width}×{height} (got {inner_w}×{inner_h}) - "
          "screen too small? Exports still render at the target size, but won't match the window.")
    return False


# kiosk: hide Grafana chrome. hideLogo: hide the "Powered by Grafana" ribbon kiosk mode shows since 12.4.
EXPORT_URL_PARAMS = ("kiosk", "hideLogo")


def _missing_export_params(url: str) -> list[str]:
    present = parse_qs(urlsplit(url).query, keep_blank_values=True)
    return [p for p in EXPORT_URL_PARAMS if p not in present]


def _with_params(url: str, params: list[str]) -> str:
    parts = urlsplit(url)
    query = "&".join([parts.query, *params] if parts.query else params)
    return urlunsplit(parts._replace(query=query))


def _wait_for_panels(driver, timeout: float = 30):
    """Wait until no Grafana panel shows a loading indicator (slow queries)."""
    start = time.monotonic()
    seen = False
    while time.monotonic() - start < timeout:
        try:
            loading = driver.find_elements(By.CSS_SELECTOR, PANEL_LOADING_SELECTOR)
        except Exception:
            return
        if not loading:
            break
        seen = True
        time.sleep(0.5)
    else:
        print(f"⚠️  Panels still loading after {timeout:.0f}s, exporting anyway")
        return
    if seen:
        print(f"⏳ Waited {time.monotonic() - start:.1f}s for panels to finish loading")


def _output_name(driver) -> str:
    """'<dashboard title>_<timestamp>' from the page title ('Title - Dashboards - Grafana')."""
    try:
        title = driver.title.split(" - ")[0]
    except Exception:
        title = ""
    slug = re.sub(r"[^\w\- ]+", "", title).strip().replace(" ", "_")[:60] or "grafana_export"
    return f"{slug}_{time.strftime('%Y%m%d_%H%M%S')}"


# Full content height: Grafana (13+) scrolls an inner container rather than the
# document, so document.scrollHeight alone misses the overflow.
_CONTENT_HEIGHT_JS = """
    let extra = document.documentElement.scrollHeight - innerHeight;
    for (const e of document.querySelectorAll('*')) {
        if (e.clientHeight < innerHeight / 2) continue;  // skip legends, small widgets
        if (!/(auto|scroll)/.test(getComputedStyle(e).overflowY)) continue;
        extra = Math.max(extra, e.scrollHeight - e.clientHeight);
    }
    return innerHeight + Math.max(0, Math.ceil(extra));
"""
MAX_PAPER_HEIGHT = 15000  # CSS px; only needs to hold whatever overlaps the visible frame

EXPORT_STYLE_ID = "grafana-png-export-style"

_HEADER_COUNT_JS = "return document.querySelectorAll('header').length"


def _enter_kiosk_in_place(driver, url: str) -> bool:
    """Switch to `url` (kiosk/hideLogo) via client-side navigation instead of a reload,
    so unsaved view state - e.g. series hidden by clicking the legend - survives.
    Returns False (with the URL change undone) if Grafana's chrome didn't react."""
    if driver.execute_script(_HEADER_COUNT_JS) == 0:
        return False  # can't tell whether kiosk took effect on this Grafana version
    driver.execute_script("""
        history.pushState(history.state, '', arguments[0]);
        dispatchEvent(new PopStateEvent('popstate', {state: history.state}));
    """, url)
    try:
        WebDriverWait(driver, 3).until(lambda d: d.execute_script(_HEADER_COUNT_JS) == 0)
        return True
    except TimeoutException:
        driver.execute_script("history.back()")
        return False


def _exit_kiosk_in_place(driver, original_url: str):
    """Undo _enter_kiosk_in_place: restore the URL, then press Esc - Grafana only leaves
    kiosk mode on Esc, not when the param disappears. Reload if anything is off."""
    driver.execute_script("history.back()")
    time.sleep(0.5)
    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    time.sleep(1)
    if unquote(driver.current_url) != unquote(original_url) or driver.execute_script(_HEADER_COUNT_JS) == 0:
        print("⚠️  In-place kiosk exit incomplete, reloading original URL")
        driver.get(original_url)


def do_export(driver, output_dir: str, dpr: int = 4, viewport=EXPORT_VIEWPORT) -> str:
    pdftoppm = _find_pdftoppm()  # fail fast, before touching the page
    original_url = driver.current_url
    kiosk_mode = None  # None | "in-place" | "reload"
    width, height = viewport
    metrics = {"width": width, "height": height, "deviceScaleFactor": dpr, "mobile": False}

    try:
        # Undo any manual resize, so the export matches the window
        if not fit_window_to_viewport(driver, viewport):
            notify(f"Window can't fit a {width}x{height} page on this screen - export won't match what you see")
        # Same size as the window (no re-layout); only raises the pixel ratio for sharp canvases.
        driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", metrics)
        missing = _missing_export_params(original_url)
        if missing:
            export_url = _with_params(original_url, missing)
            if _enter_kiosk_in_place(driver, export_url):
                kiosk_mode = "in-place"
                time.sleep(1)
            else:
                print("ℹ️  In-place kiosk not available, reloading (unsaved view changes are lost)")
                driver.get(export_url)
                kiosk_mode = "reload"
                time.sleep(5)
        else:
            time.sleep(1)

        _wait_for_panels(driver)

        # Wait for the time picker label to be populated (React renders it async)
        try:
            WebDriverWait(driver, 10).until(
                lambda d: d.find_element(
                    By.CSS_SELECTOR, '[data-testid="data-testid TimePicker Open Button"]'
                ).text.strip()
            )
        except Exception:
            pass  # proceed even if selector doesn't match this Grafana version

        driver.execute_script("""
            const style = document.createElement('style');
            style.id = arguments[0];
            style.textContent = `
                [data-testid="data-testid RefreshPicker run button"],
                [data-testid="data-testid RefreshPicker interval button"] { display: none !important; }
                /* Dashboard tab bar (grouped dashboards); the active tab's panels are still shown */
                div:has(> [role="tablist"] [data-tab-activation-key]) { display: none !important; }
                /* Panel "⋮" menu, which appears on whichever panel the mouse is over */
                [data-testid^="data-testid Panel menu "] { visibility: hidden !important; }
                /* Panel resize handles (bottom-right corner marks) */
                .scene-resize-handle, .react-resizable-handle { display: none !important; }
                /* "Add variable" (+) button; its row is hidden too when it holds nothing else,
                   so dashboards with variables keep them */
                .dashboard-canvas-add-button { display: none !important; }
                [data-testid="dashboard controls"] > div:has(> .dashboard-canvas-add-button:only-child) {
                    display: none !important;
                }
                @media print {
                    [data-testid="data-testid TimePicker Open Button"] > div { display: block !important; }
                }
            `;
            document.head.appendChild(style);
        """, EXPORT_STYLE_ID)
        time.sleep(1)

        # Print on one page tall enough for all content, then crop the visible frame in
        # pdftoppm. (A viewport-sized page doesn't work: Chrome won't split a canvas across
        # a page break, so a chart crossing the bottom edge moves to page 2 and prints blank.)
        paper_height = min(driver.execute_script(_CONTENT_HEIGHT_JS), MAX_PAPER_HEIGHT)
        pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True,
            "paperWidth": width / 96,
            "paperHeight": paper_height / 96,
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
            "scale": 1.0,
        })

        os.makedirs(output_dir, exist_ok=True)
        prefix = os.path.join(output_dir, _output_name(driver))

        with tempfile.TemporaryDirectory(prefix="grafana-export-") as tmp:
            pdf_path = os.path.join(tmp, "export.pdf")
            with open(pdf_path, "wb") as f:
                f.write(base64.b64decode(pdf_data["data"]))
            result = subprocess.run(
                [pdftoppm, "-r", str(PNG_DPI), "-png", "-singlefile",
                 "-x", "0", "-y", "0",
                 "-W", str(round(width / 96 * PNG_DPI)), "-H", str(round(height / 96 * PNG_DPI)),
                 pdf_path, prefix],
                capture_output=True, creationflags=_NO_WINDOW,
            )
        if result.returncode != 0:
            raise RuntimeError(f"pdftoppm failed: {result.stderr.decode(errors='replace')}")

        return prefix + ".png"
    finally:
        # Without a reload the injected CSS would otherwise stay in the user's view
        try:
            driver.execute_script("document.getElementById(arguments[0])?.remove()", EXPORT_STYLE_ID)
        except Exception as e:
            print(f"⚠️  Could not remove export CSS: {e}")
        try:
            if kiosk_mode == "in-place":
                _exit_kiosk_in_place(driver, original_url)
            elif kiosk_mode == "reload":
                driver.get(original_url)
        except Exception as e:
            print(f"⚠️  Could not restore original URL: {e}")
        try:
            driver.execute_cdp_cmd("Emulation.clearDeviceMetricsOverride", {})
        except Exception as e:
            print(f"⚠️  Could not restore viewport: {e}")


def _export_and_report(driver, args) -> bool:
    notify("Exporting…")
    try:
        path = do_export(driver, args.output_dir, args.dpr, args.format)
    except Exception as e:
        first_line = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        notify(f"Export failed: {first_line}")
        print(f"❌ Export failed: {e}")
        return False
    copied = args.clipboard and copy_png_to_clipboard(path)
    notify(f"PNG saved{' and copied' if copied else ''}: {os.path.basename(path)}")
    print(f"🎉 PNG saved: {path}{' (copied to clipboard)' if copied else ''}")
    return True


def _consume_trigger(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        os.remove(path)
    except OSError:
        pass
    return True


def _run_loop(driver, args):
    """Wait for export/stop requests: trigger files on Windows, signals (SIGUSR1/SIGTERM) elsewhere.
    A periodic keep-alive keeps the ChromeDriver session warm and detects a closed browser."""
    export_count = 0
    export_event = threading.Event()
    stop_event = threading.Event()

    if SYSTEM == "Windows":
        print("✅ Session ready. Watching for trigger files...")
    else:
        signal.signal(signal.SIGUSR1, lambda *_: export_event.set())
        signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
        print("✅ Session ready. Listening for export signals...")
    width, height = args.format
    notify(f"Session ready ({width}x{height}) - navigate to a dashboard, then use 'Export Grafana PNG' in Raycast")

    last_keepalive = time.monotonic()
    keepalive_failures = 0
    try:
        while True:
            if SYSTEM == "Windows":
                if _consume_trigger(STOP_TRIGGER):
                    stop_event.set()
                if _consume_trigger(EXPORT_TRIGGER):
                    export_event.set()
            if stop_event.is_set():
                break

            if export_event.wait(timeout=0.5):
                export_event.clear()
                if _export_and_report(driver, args):
                    export_count += 1
                last_keepalive = time.monotonic()
            elif time.monotonic() - last_keepalive >= KEEPALIVE_INTERVAL:
                try:
                    driver.execute_script("return 1")
                    keepalive_failures = 0
                except Exception as e:
                    keepalive_failures += 1
                    print(f"⚠️ Keep-alive failed ({keepalive_failures}): {e}")
                    if keepalive_failures >= KEEPALIVE_MAX_FAILURES:
                        print("❌ Browser connection lost, ending session")
                        break
                last_keepalive = time.monotonic()
    except KeyboardInterrupt:
        pass

    return export_count


def main():
    default_browser = platform_default_browser()
    parser = argparse.ArgumentParser(description="Grafana → PNG exporter")
    parser.add_argument("--browser", choices=["chrome", "brave", "edge"], default=default_browser,
                        help=f"Browser to use (default on this OS: {default_browser})")
    parser.add_argument("--user-data-dir", help="Override browser profile directory")
    parser.add_argument("--output-dir", default=os.path.expanduser("~/Downloads"),
                        help="Directory to save PNGs (default: ~/Downloads)")
    parser.add_argument("--dpr", type=int, default=4,
                        help="Device pixel ratio for canvas rendering (default: 4)")
    parser.add_argument("--format", type=parse_format, default=DEFAULT_FORMAT,
                        help=f"Export format: {', '.join(EXPORT_FORMATS)}, or WIDTHxHEIGHT in CSS px "
                             f"(default: {DEFAULT_FORMAT}). The browser window is sized to match.")
    parser.add_argument("--no-clipboard", dest="clipboard", action="store_false",
                        help="Don't copy exported PNGs to the clipboard")

    args = parser.parse_args()

    # Claim the session before the (slow) browser launch, so Raycast commands
    # see it immediately and a stop requested during startup isn't discarded.
    os.makedirs(DATA_DIR, exist_ok=True)
    for stale in (EXPORT_TRIGGER, STOP_TRIGGER):
        try:
            os.remove(stale)
        except OSError:
            pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    driver = None
    export_count = 0
    try:
        print(f"✅ Browser: {args.browser.upper()}")
        width, height = args.format
        print(f"✅ Format: {width}×{height} (PNG {round(width / 96 * PNG_DPI)}×{round(height / 96 * PNG_DPI)})")
        driver = create_driver(args.browser, args.user_data_dir, args.format)
        export_count = _run_loop(driver, args)
    except Exception as e:
        notify(f"Session failed: {e}")
        raise
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        if driver is not None:
            chromedriver_pid = None
            try:
                chromedriver_pid = driver.service.process.pid
            except Exception:
                pass
            try:
                driver.quit()
            except Exception:
                pass
            if SYSTEM == "Windows" and chromedriver_pid:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(chromedriver_pid)],
                    capture_output=True,
                )
            notify(f"Session ended - {export_count} PNG(s) exported")
        print(f"\n✅ Done. Exported {export_count} PNG(s).")


if __name__ == "__main__":
    main()
