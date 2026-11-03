#!/usr/bin/env python3
"""
Fetch ONE sample of the e-vaskeri board and append it to evaskeri_log.csv.

Built to run as a GitHub Actions scheduled job: it logs in, reads the live
board once, appends one row per machine, and exits. Standard library only, so
the Actions job needs no `pip install`.

Credentials come from environment variables (GitHub Secrets):
    EVASKERI_USER, EVASKERI_PASS

CSV columns:
    timestamp_iso, epoch, machine, kind, status, in_use, remaining_min
"""

import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "https://back-nortec.datpro2.dk"
APP  = "TUK"
OUT  = "evaskeri_log.csv"

HEADERS = {
    "accept": "*/*",
    "origin": "https://e-vaskeri.dk",
    "referer": "https://e-vaskeri.dk/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/156.0.0.0 Safari/537.36"),
}
CSV_FIELDS = ["timestamp_iso", "epoch", "machine", "kind",
              "status", "in_use", "remaining_min"]


def _get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def login(username, password):
    q = urllib.parse.urlencode({
        "App": APP, "session": "", "username": username, "password": password,
        "language": "da", "guid": "", "tick": int(time.time() * 1000),
        "domain": "https://e-vaskeri.dk", "native": "false",
    })
    data = _get_json(f"{BASE}/User/Login4/?{q}&.json")
    if data.get("Return") != 100 or not data.get("Session"):
        # never echo the URL/credentials
        raise RuntimeError(f"login rejected (Return={data.get('Return')})")
    return data["Session"]


def fetch_live(session):
    url = (f"{BASE}/Location/Live5/"
           f"?App={APP}&session={session}&tick={int(time.time()*1000)}"
           f"&native=false&.json")
    return _get_json(url)


def parse_machines(data):
    rows = []
    for section in data.get("Sections", []):
        for row in section.get("Rows", []):
            for unit in row.get("Units", []):
                name   = unit.get("Text", "?")
                status = unit.get("Status", "?").rstrip(".")
                proc   = unit.get("Process", "") or ""
                in_use = 1 if "use" in status.lower() else 0
                m = re.search(r"(\d+)", proc)
                remaining = int(m.group(1)) if (in_use and m) else ""
                kind = ("washer" if "wash" in name.lower()
                        else "dryer" if "dry" in name.lower() else "other")
                rows.append({"machine": name, "kind": kind, "status": status,
                             "in_use": in_use, "remaining_min": remaining})
    return rows


def append_rows(path, machine_rows):
    new_file = not os.path.exists(path)
    now = time.time()
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now))  # UTC in the log
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if new_file:
            w.writeheader()
        for r in machine_rows:
            w.writerow({"timestamp_iso": iso, "epoch": int(now), **r})


def main():
    user = os.environ.get("EVASKERI_USER")
    pw   = os.environ.get("EVASKERI_PASS")
    if not user or not pw:
        sys.exit("Missing EVASKERI_USER / EVASKERI_PASS environment variables.")

    try:
        session = login(user, pw)
        data = fetch_live(session)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP error {e.code} talking to backend.")
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e.reason}")

    if data.get("Return") != 100 or not data.get("Sections"):
        sys.exit(f"Unexpected Live5 response (Return={data.get('Return')}).")

    rows = parse_machines(data)
    append_rows(OUT, rows)
    free = sum(1 for r in rows if r["in_use"] == 0
               and "offline" not in r["status"].lower())
    print(f"sampled {len(rows)} machines, {free} free -> appended to {OUT}")


if __name__ == "__main__":
    main()
