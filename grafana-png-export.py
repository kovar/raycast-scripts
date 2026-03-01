#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "selenium>=4.20"
# ]
# ///

import sys
import time
import os
import base64
import platform
import argparse
import socket
import signal
import subprocess
import threading
import glob

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

REMOTE_DEBUG_PORT = 9222
DATA_DIR = os.path.expanduser("~/.grafana-png-exporter")
PID_FILE = os.path.join(DATA_DIR, "session.pid")
EXPORT_TRIGGER = os.path.join(DATA_DIR, "export.trigger")
STOP_TRIGGER = os.path.join(DATA_DIR, "stop.trigger")


def platform_default_browser():
    system = platform.system().lower()
    if system == "darwin":
        return "brave"
    elif system == "windows":
        return "brave"
    return "chrome"


def get_browser_config(browser_name: str):
    automation_profile = os.path.join(DATA_DIR, f"{browser_name}-profile")
    os.makedirs(automation_profile, exist_ok=True)

    system = platform.system().lower()
    if browser_name == "brave":
        if system == "darwin":
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
        binary = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" if system == "darwin" \
            else r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        return binary, automation_profile

    else:  # chrome
        return None, automation_profile


_WINDOWS_TO_IANA = {
    "AUS Central Standard Time": "Australia/Darwin",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "Afghanistan Standard Time": "Asia/Kabul",
    "Alaskan Standard Time": "America/Anchorage",
    "Arab Standard Time": "Asia/Riyadh",
    "Arabian Standard Time": "Asia/Dubai",
    "Arabic Standard Time": "Asia/Baghdad",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "Atlantic Standard Time": "America/Halifax",
    "Azerbaijan Standard Time": "Asia/Baku",
    "Azores Standard Time": "Atlantic/Azores",
    "Canada Central Standard Time": "America/Regina",
    "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "Caucasus Standard Time": "Asia/Yerevan",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "Central America Standard Time": "America/Guatemala",
    "Central Asia Standard Time": "Asia/Almaty",
    "Central Brazilian Standard Time": "America/Cuiaba",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "Central Pacific Standard Time": "Pacific/Guadalcanal",
    "Central Standard Time": "America/Chicago",
    "Central Standard Time (Mexico)": "America/Mexico_City",
    "China Standard Time": "Asia/Shanghai",
    "Dateline Standard Time": "Etc/GMT+12",
    "E. Africa Standard Time": "Africa/Nairobi",
    "E. Australia Standard Time": "Australia/Brisbane",
    "E. Europe Standard Time": "Asia/Nicosia",
    "E. South America Standard Time": "America/Sao_Paulo",
    "Eastern Standard Time": "America/New_York",
    "Eastern Standard Time (Mexico)": "America/Cancun",
    "Egypt Standard Time": "Africa/Cairo",
    "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
    "FLE Standard Time": "Europe/Kiev",
    "Fiji Standard Time": "Pacific/Fiji",
    "GMT Standard Time": "Europe/London",
    "GTB Standard Time": "Europe/Bucharest",
    "Georgian Standard Time": "Asia/Tbilisi",
    "Greenland Standard Time": "America/Godthab",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "India Standard Time": "Asia/Calcutta",
    "Iran Standard Time": "Asia/Tehran",
    "Israel Standard Time": "Asia/Jerusalem",
    "Jordan Standard Time": "Asia/Amman",
    "Korea Standard Time": "Asia/Seoul",
    "Libya Standard Time": "Africa/Tripoli",
    "Line Islands Standard Time": "Pacific/Kiritimati",
    "Magadan Standard Time": "Asia/Magadan",
    "Mauritius Standard Time": "Indian/Mauritius",
    "Middle East Standard Time": "Asia/Beirut",
    "Montevideo Standard Time": "America/Montevideo",
    "Morocco Standard Time": "Africa/Casablanca",
    "Mountain Standard Time": "America/Denver",
    "Mountain Standard Time (Mexico)": "America/Chihuahua",
    "Myanmar Standard Time": "Asia/Rangoon",
    "N. Central Asia Standard Time": "Asia/Novosibirsk",
    "Namibia Standard Time": "Africa/Windhoek",
    "Nepal Standard Time": "Asia/Katmandu",
    "New Zealand Standard Time": "Pacific/Auckland",
    "Newfoundland Standard Time": "America/St_Johns",
    "North Asia East Standard Time": "Asia/Irkutsk",
    "North Asia Standard Time": "Asia/Krasnoyarsk",
    "Pacific SA Standard Time": "America/Santiago",
    "Pacific Standard Time": "America/Los_Angeles",
    "Pacific Standard Time (Mexico)": "America/Santa_Isabel",
    "Pakistan Standard Time": "Asia/Karachi",
    "Paraguay Standard Time": "America/Asuncion",
    "Romance Standard Time": "Europe/Paris",
    "Russia Time Zone 11": "Asia/Kamchatka",
    "Russia Time Zone 3": "Europe/Samara",
    "Russia Time Zone 9": "Asia/Yakutsk",
    "Russian Standard Time": "Europe/Moscow",
    "SA Eastern Standard Time": "America/Cayenne",
    "SA Pacific Standard Time": "America/Bogota",
    "SA Western Standard Time": "America/La_Paz",
    "SE Asia Standard Time": "Asia/Bangkok",
    "Samoa Standard Time": "Pacific/Apia",
    "Singapore Standard Time": "Asia/Singapore",
    "South Africa Standard Time": "Africa/Johannesburg",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Syria Standard Time": "Asia/Damascus",
    "Taipei Standard Time": "Asia/Taipei",
    "Tasmania Standard Time": "Australia/Hobart",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Tonga Standard Time": "Pacific/Tongatapu",
    "Turkey Standard Time": "Europe/Istanbul",
    "US Eastern Standard Time": "America/Indiana/Indianapolis",
    "US Mountain Standard Time": "America/Phoenix",
    "UTC": "Etc/UTC",
    "UTC+12": "Etc/GMT-12",
    "UTC-02": "Etc/GMT+2",
    "UTC-11": "Etc/GMT+11",
    "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar",
    "Venezuela Standard Time": "America/Caracas",
    "Vladivostok Standard Time": "Asia/Vladivostok",
    "W. Australia Standard Time": "Australia/Perth",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "W. Europe Standard Time": "Europe/Berlin",
    "West Asia Standard Time": "Asia/Tashkent",
    "West Pacific Standard Time": "Pacific/Port_Moresby",
    "Yakutsk Standard Time": "Asia/Yakutsk",
}


def get_system_timezone() -> str | None:
    """Return the local IANA timezone ID (e.g. 'Europe/Berlin'), or None if unavailable."""
    if platform.system() == "darwin":
        try:
            result = subprocess.run(["readlink", "/etc/localtime"], capture_output=True, text=True)
            tz = result.stdout.strip()
            if "zoneinfo/" in tz:
                return tz.split("zoneinfo/")[-1]
        except Exception:
            pass
    elif platform.system() == "Windows":
        try:
            result = subprocess.run(["tzutil", "/g"], capture_output=True, text=True)
            win_tz = result.stdout.strip()
            iana = _WINDOWS_TO_IANA.get(win_tz)
            if not iana:
                print(f"⚠️  Unknown Windows timezone '{win_tz}', skipping timezone override")
            return iana
        except Exception:
            pass
    return None


def is_debug_port_open(port=REMOTE_DEBUG_PORT):
    try:
        with socket.create_connection(("localhost", port), timeout=1):
            return True
    except OSError:
        return False


def apply_session_settings(driver, dpr: int = 4):
    tz = get_system_timezone()
    if tz:
        driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": tz})
        print(f"✅ Timezone: {tz}")

    driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
        "width": 1920,
        "height": 1080,
        "deviceScaleFactor": dpr,
        "mobile": False,
    })
    print(f"✅ Device pixel ratio: {dpr}x")


def create_driver(browser_name: str, user_data_dir: str = None, dpr: int = 4):
    binary, automation_profile = get_browser_config(browser_name)

    def base_options():
        opts = Options()
        if binary:
            opts.binary_location = binary
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-background-timer-throttling")
        opts.add_argument("--disable-renderer-backgrounding")
        opts.add_argument("--disable-backgrounding-occluded-windows")
        if platform.system() == "Windows":
            opts.add_argument("--force-device-scale-factor=1")
        return opts

    if is_debug_port_open():
        opts = base_options()
        opts.debugger_address = f"localhost:{REMOTE_DEBUG_PORT}"
        try:
            driver = webdriver.Chrome(options=opts)
            print(f"✅ Connected to existing {browser_name.capitalize()} window (port {REMOTE_DEBUG_PORT})")
            apply_session_settings(driver, dpr)
            return driver
        except Exception:
            pass

    profile_dir = user_data_dir or automation_profile
    opts = base_options()
    opts.add_argument(f"--user-data-dir={profile_dir}")
    driver = webdriver.Chrome(options=opts)
    print(f"✅ Launched {browser_name.capitalize()} (automation profile: {profile_dir})")
    apply_session_settings(driver, dpr)
    return driver


def notify(message: str):
    if platform.system() == "darwin":
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "Grafana Exporter"'],
            capture_output=True,
        )
    elif platform.system() == "Windows":
        subprocess.run(
            ["powershell", "-Command",
             f'Add-Type -AssemblyName System.Windows.Forms; '
             f'$n = New-Object System.Windows.Forms.NotifyIcon; '
             f'$n.Icon = [System.Drawing.SystemIcons]::Information; '
             f'$n.Visible = $true; '
             f'$n.ShowBalloonTip(5000, "Grafana Exporter", "{message}", 1); '
             f'Start-Sleep -Milliseconds 500; $n.Dispose()'],
            capture_output=True,
        )


def auto_login(driver, username: str, password: str):
    print("🔑 Attempting auto-login...")
    try:
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="password"]'))
        )
    except Exception:
        print("⚠️  Login form not found (already logged in?)")
        return

    for sel in ['input[name="user"]', 'input[name="username"]',
                'input[placeholder*="email" i]', 'input[placeholder*="username" i]']:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            elem.clear()
            elem.send_keys(username)
            break
        except:
            continue

    driver.find_element(By.CSS_SELECTOR, 'input[type="password"]').send_keys(password)

    for sel in ['button[type="submit"]', 'button[data-testid="login-button"]']:
        try:
            driver.find_element(By.CSS_SELECTOR, sel).click()
            time.sleep(4)
            print("✅ Login submitted")
            return
        except:
            continue
    print("⚠️  Could not submit login form")


def _find_pdftoppm() -> str:
    import shutil
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
    ]:
        candidates.extend(glob.glob(pattern))
    for c in candidates:
        if os.path.isfile(c):
            return c
    if platform.system() == "Windows":
        raise RuntimeError("pdftoppm not found. Install poppler: winget install oschwartz10612.Poppler")
    raise RuntimeError("pdftoppm not found. Install poppler: brew install poppler")


def do_export(driver, output_dir: str) -> str:
    cur = driver.current_url

    if "kiosk" not in cur:
        kiosk_url = cur + ("&kiosk" if "?" in cur else "?kiosk")
        driver.get(kiosk_url)
        time.sleep(5)

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
        style.textContent = `
            [data-testid="data-testid RefreshPicker run button"],
            [data-testid="data-testid RefreshPicker interval button"] { display: none !important; }
            @media print {
                [data-testid="data-testid TimePicker Open Button"] > div { display: block !important; }
            }
        `;
        document.head.appendChild(style);
    """)
    time.sleep(1)

    w = driver.execute_script("return document.documentElement.scrollWidth")
    h = driver.execute_script("return document.documentElement.scrollHeight")
    print(f"✅ Content size: {w}x{h} CSS px")

    pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {
        "printBackground": True,
        "paperWidth": w / 96,
        "paperHeight": h / 96,
        "marginTop": 0,
        "marginBottom": 0,
        "marginLeft": 0,
        "marginRight": 0,
        "scale": 1.0,
    })

    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    prefix = os.path.join(output_dir, f"grafana_export_{timestamp}")
    pdf_path = prefix + ".pdf"

    with open(pdf_path, "wb") as f:
        f.write(base64.b64decode(pdf_data["data"]))

    pdftoppm = _find_pdftoppm()
    result = subprocess.run(
        [pdftoppm, "-scale-to-x", "6000", "-scale-to-y", "-1", "-png", "-singlefile", pdf_path, prefix],
        capture_output=True,
    )
    os.remove(pdf_path)
    if result.returncode != 0:
        raise RuntimeError(f"pdftoppm failed: {result.stderr.decode()}")

    driver.get(cur)
    time.sleep(2)

    return prefix + ".png"


def _run_loop(driver, args):
    export_count = 0
    notify("Session ready — navigate to a dashboard, then use 'Export Grafana PNG' in Raycast")

    if platform.system() == "Windows":
        print("✅ Session ready. Watching for trigger files...")
        try:
            last_keepalive = time.monotonic()
            keepalive_failures = 0
            while True:
                if os.path.exists(STOP_TRIGGER):
                    try:
                        os.remove(STOP_TRIGGER)
                    except OSError:
                        pass
                    break
                if os.path.exists(EXPORT_TRIGGER):
                    try:
                        os.remove(EXPORT_TRIGGER)
                    except OSError:
                        pass
                    try:
                        path = do_export(driver, args.output_dir)
                        export_count += 1
                        notify(f"PNG saved: {os.path.basename(path)}")
                        print(f"🎉 PNG saved: {path}")
                    except Exception as e:
                        notify(f"Export failed: {e}")
                        print(f"❌ Export failed: {e}")
                    last_keepalive = time.monotonic()
                elif time.monotonic() - last_keepalive >= 15:
                    try:
                        driver.execute_script("return 1")
                        keepalive_failures = 0
                    except Exception as e:
                        keepalive_failures += 1
                        print(f"⚠️ Keep-alive failed ({keepalive_failures}): {e}")
                        if keepalive_failures >= 3:
                            print("❌ Browser connection lost, ending session")
                            break
                    last_keepalive = time.monotonic()
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    else:
        print("✅ Session ready. Listening for export signals...")
        _export_event = threading.Event()
        _stop_event = threading.Event()

        def _on_export(signum, frame):
            _export_event.set()

        def _on_stop(signum, frame):
            _stop_event.set()

        signal.signal(signal.SIGUSR1, _on_export)
        signal.signal(signal.SIGTERM, _on_stop)

        try:
            while not _stop_event.is_set():
                if _export_event.wait(timeout=0.5):
                    _export_event.clear()
                    try:
                        path = do_export(driver, args.output_dir)
                        export_count += 1
                        notify(f"PNG saved: {os.path.basename(path)}")
                        print(f"🎉 PNG saved: {path}")
                    except Exception as e:
                        notify(f"Export failed: {e}")
                        print(f"❌ Export failed: {e}")
        except KeyboardInterrupt:
            pass

    return export_count


def main():
    default_browser = platform_default_browser()
    parser = argparse.ArgumentParser(description="Grafana → PNG exporter")
    parser.add_argument("--browser", choices=["chrome", "brave", "edge"], default=default_browser,
                        help=f"Browser to use (default on this OS: {default_browser})")
    parser.add_argument("--username", help="Grafana username (for auto-login)")
    parser.add_argument("--password", help="Grafana password (for auto-login)")
    parser.add_argument("--grafana-url", default="http://localhost:3000",
                        help="Grafana base URL, used when auto-login credentials are provided")
    parser.add_argument("--user-data-dir", help="Override browser profile directory")
    parser.add_argument("--output-dir", default=os.path.expanduser("~/Downloads"),
                        help="Directory to save PNGs (default: ~/Downloads)")
    parser.add_argument("--dpr", type=int, default=4,
                        help="Device pixel ratio for canvas rendering (default: 4)")

    args = parser.parse_args()
    print(f"✅ Browser: {args.browser.upper()}")

    driver = create_driver(args.browser, args.user_data_dir, args.dpr)

    if args.username and args.password:
        driver.get(f"{args.grafana_url}/login")
        auto_login(driver, args.username, args.password)

    os.makedirs(DATA_DIR, exist_ok=True)
    for stale in (EXPORT_TRIGGER, STOP_TRIGGER):
        try:
            os.remove(stale)
        except OSError:
            pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    try:
        export_count = _run_loop(driver, args)
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        chromedriver_pid = None
        try:
            chromedriver_pid = driver.service.process.pid
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass
        if platform.system() == "Windows" and chromedriver_pid:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(chromedriver_pid)],
                capture_output=True,
            )
        notify(f"Session ended — {export_count} PNG(s) exported")
        print(f"\n✅ Done. Exported {export_count} PNG(s).")


if __name__ == "__main__":
    main()
