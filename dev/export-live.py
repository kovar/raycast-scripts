#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "selenium>=4.20",
#   "tzlocal>=5.0",
# ]
# ///
"""Dev tool: run the *current* grafana-png-export.py export code against the
browser of an already-running session, without restarting it.

Attaches to the session browser via its DevTools port (from DevToolsActivePort
in the automation profile), exports the open tab, prints the PNG path.
No clipboard copy, no notifications; the session itself is left untouched.

    uv run dev/export-live.py [--format 16:9] [--output-dir DIR] [--browser brave]
"""

import argparse
import importlib.util
import os
import sys

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "grafana-png-export.py")


def load_exporter():
    spec = importlib.util.spec_from_file_location("grafana_png_export", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    gpe = load_exporter()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--browser", default=gpe.platform_default_browser())
    parser.add_argument("--format", type=gpe.parse_format, default=gpe.DEFAULT_FORMAT,
                        help="Must match the format the session was started with")
    parser.add_argument("--output-dir", default=os.path.join(gpe.DATA_DIR, "dev-exports"))
    args = parser.parse_args()

    port_file = os.path.join(gpe.DATA_DIR, f"{args.browser}-profile", "DevToolsActivePort")
    try:
        with open(port_file) as f:
            port = f.readline().strip()
    except OSError:
        sys.exit(f"No running session browser ({port_file} not found)")

    opts = Options()
    opts.debugger_address = f"127.0.0.1:{port}"
    driver = webdriver.Chrome(options=opts)
    try:
        gpe.notify = lambda message: None
        # CDP emulation overrides are per connection: re-apply the session's timezone.
        # (do_export applies and clears its own viewport override.)
        gpe.apply_session_settings(driver)
        print(f"Exporting: {driver.current_url}")
        path = gpe.do_export(driver, args.output_dir, viewport=args.format)
        print(path)
    finally:
        # Stop only our chromedriver; quit() could close the session's browser.
        driver.service.stop()


if __name__ == "__main__":
    main()
