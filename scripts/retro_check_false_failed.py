"""Retrospective audit of false-'no form fields found' failures.

Reads the latest reports/manual_<run>.json (or visit_<run>.json), finds
entries that failed with reason "no form fields found" (path_taken
"full_form"), re-visits each URL fresh, and asks Naukri's own
'already-applied' marker whether the application actually went through.

Outputs reports/retro_check_<run>.json + a CSV with one row per URL.

NOTE: this deliberately does NOT import apply_jobs. That module launches the
Firefox driver at import time (top-level `webdriver.Firefox(...)`), so
importing it would open a second live browser session before this script's own
logic runs. The driver bootstrap is copied here instead; config_loader and
state are safe to import (no launch-on-import side effects).
"""

import os
import sys
import glob
import json
import shutil
import time
import argparse
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    InvalidSessionIdException,
    WebDriverException,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config_loader import load_config  # noqa: E402  (safe: no browser on import)

TARGET_REASON = "no form fields found"
TARGET_PATH = "full_form"


def _latest_report(report_dir: str, prefix: str) -> str:
    pattern = os.path.join(report_dir, f"{prefix}_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"No {prefix}_*.json reports found in {report_dir!r}")
    return files[-1]


def _collect_urls(report_dir: str, use_visit: bool) -> list:
    prefix = "visit" if use_visit else "manual"
    path = _latest_report(report_dir, prefix)
    print(f"[retro] reading {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("results") if use_visit else data.get("items", [])
    urls = []
    for it in items:
        if it.get("reason") == TARGET_REASON and it.get("path_taken") == TARGET_PATH:
            u = it.get("url")
            if u and u not in urls:
                urls.append(u)
    print(f"[retro] {len(urls)} candidate URL(s) with {TARGET_REASON!r}")
    return urls


def _already_applied(driver, url: str, nav_wait: float) -> bool:
    try:
        driver.get(url)
        time.sleep(nav_wait)
        return bool(driver.find_elements(By.ID, "already-applied"))
    except (InvalidSessionIdException, WebDriverException):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visit", action="store_true",
                        help="Read visit_*.json instead of manual_*.json")
    parser.add_argument("--max", type=int, default=None,
                        help="Cap the number of URLs checked (default: all)")
    args = parser.parse_args()

    config = load_config()
    browser = config["browser"]
    report_dir = os.path.join(ROOT, config["reports"]["dir"])
    nav_wait = config["timing"]["nav_wait"]

    urls = _collect_urls(report_dir, args.visit)
    if args.max is not None:
        urls = urls[: args.max]

    driver_path = shutil.which("geckodriver")
    if not driver_path:
        raise SystemExit("geckodriver not found on PATH.")
    binary = browser["binary"] or shutil.which("firefox") or "/opt/firefox/firefox"

    service = Service(driver_path)
    options = Options()
    options.binary_location = binary
    options.profile = FirefoxProfile(browser["profile_path"])
    options.add_argument("--no-default-browser-check")

    driver = webdriver.Firefox(service=service, options=options)

    run = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []
    try:
        for idx, url in enumerate(urls, start=1):
            applied = _already_applied(driver, url, nav_wait)
            status = "already_applied" if applied else "failed"
            results.append({"url": url, "status": status, "original_reason": TARGET_REASON})
            print(f"[retro] [{idx}/{len(urls)}] {status}: {url}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    os.makedirs(report_dir, exist_ok=True)
    json_path = os.path.join(report_dir, f"retro_check_{run}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_id": run,
            "generated_at": datetime.now().isoformat(),
            "count": len(results),
            "summary": {
                "already_applied": sum(1 for r in results if r["status"] == "already_applied"),
                "failed": sum(1 for r in results if r["status"] == "failed"),
            },
            "items": results,
        }, f, indent=2)
    print(f"[retro] wrote {json_path}")

    csv_path = os.path.join(report_dir, f"retro_check_{run}.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write("url,status,original_reason\n")
        for r in results:
            f.write(f'{r["url"]},{r["status"]},{r["original_reason"]}\n')
    print(f"[retro] wrote {csv_path}")


if __name__ == "__main__":
    main()
