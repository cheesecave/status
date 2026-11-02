#!/usr/bin/env python3
"""Make a demo site with synthetic data of a made-up instance, for the screenshots of the README (and for trying the page).

usage: demo_data.py --out DIR [--scenario normal|outage]
Nothing here is real: 100 days of invented checks, a few invented incidents. Serve DIR with any static server.
"""
import argparse
import json
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_pages  # noqa: E402
import rollup  # noqa: E402
import statuslib as s  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STEP = timedelta(minutes=5)


class Gh:
    """Stands in for GitHub: the issues of the demo outage live at this made-up address."""
    def open_issue(self, title, body):
        return 12, "https://github.com/example/status/issues/12"

    def close_issue(self, number, comment):
        pass


def demo_config():
    cfg = s.load_config(ROOT / "status.config.example.json")
    cfg["name"] = "Example Hub"
    cfg["base_url"] = "https://hub.example.org"
    cfg["description"] = "Demo data of a made-up CheeseCave instance."
    cfg["links"] = {
        "header": [{"label": "Example Hub", "url": "https://hub.example.org"}],
        "footer": [{"label": "Report a problem", "url": "https://github.com/example/status/issues"},
                   {"label": "Powered by CheeseCave", "url": "https://github.com/cheesecave"}],
    }
    return cfg


def synth(cfg, now, scenario, rng):
    """100 days of 5-minute rounds, as raw records."""
    names = [c["name"] for c in cfg["components"]]
    windows = [  # (start, length, component, kind)
        (now - timedelta(days=37, hours=3), timedelta(hours=3), "Git LFS", "down"),
        (now - timedelta(days=21), timedelta(minutes=50), "Website", "slow"),
        (now - timedelta(days=9, hours=6), timedelta(hours=1, minutes=10), "Download speed", "slow"),
        (now - timedelta(days=3, hours=2), timedelta(minutes=35), "File tree", "down"),
    ]
    if scenario == "outage":
        windows.append((now - timedelta(minutes=17), timedelta(minutes=40), "Git LFS", "down"))
    base = {"Website": (90, 230), "API": (80, 210), "Repository listing": (110, 260), "File tree": (130, 300), "Git fetch": (400, 900),
            "Git LFS": (120, 280), "Small file download": (260, 620), "Download speed": (500, 1100)}
    records, t = [], now - timedelta(days=100)
    while t <= now:
        row = {}
        for n in names:
            lo, hi = base.get(n, (100, 250))
            state, ms, speed = "up", rng.randint(lo, hi), None
            if n == "Download speed":
                speed = round(rng.uniform(5.0, 11.0), 2)
            if rng.random() < 0.0012 and t < now - timedelta(minutes=20):   # the latest rounds are clean unless a scenario says otherwise
                state, ms = "degraded", rng.randint(9000, 11000)
            for start, length, who, kind in windows:
                if who == n and start <= t < start + length:
                    if kind == "down":
                        state, ms, speed = "down", None, None
                    else:
                        state, ms, speed = "degraded", rng.randint(9000, 12000), (0.3 if n == "Download speed" else None)
            row[n] = [state, ms, ms and int(ms * 0.5), speed]
        records.append({"t": s.iso(t), "c": row})
        t += STEP
    return records


def make(out, scenario="normal", seed=11):
    rng = random.Random(seed)
    cfg = demo_config()
    now = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    names = [c["name"] for c in cfg["components"]]
    data = Path(tempfile.mkdtemp())
    records = synth(cfg, now - STEP, scenario, rng)
    hourly = rollup.hourly_from_records(records, names)
    rollup.save_hourly(data, hourly, hourly)
    for r in records:
        if r["t"] >= s.iso(now - timedelta(days=cfg["raw_days"])):
            s.append_record(data, r)
    past = {"component": "Git LFS", "title": "Git LFS is down", "url": "https://github.com/example/status/issues/7", "issue": 7,
            "opened_at": s.iso(now - timedelta(days=37, hours=3)), "closed_at": s.iso(now - timedelta(days=37))}
    past2 = {"component": "File tree", "title": "File tree is down", "url": "https://github.com/example/status/issues/9", "issue": 9,
             "opened_at": s.iso(now - timedelta(days=3, hours=2)), "closed_at": s.iso(now - timedelta(days=3, hours=1, minutes=25))}
    (data / "incidents.json").write_text(json.dumps([past, past2]))

    def fetch(url, headers, timeout, max_bytes, method="GET", body=None):
        time.sleep(rng.uniform(0.08, 0.35))   # a believable response time for the latest round
        if scenario == "outage" and "lfs" in url:
            return 503, b"", 0.2, 0.0
        if "A_FILE" in url:
            return 206, b"x" * 1_048_576, 0.4, 0.12
        if "api/version" in url:
            return 200, b'{"api":"cheesecave"}', 0.1, 0.0
        if "lfs" in url:
            return 200, b'{"transfer":"basic","objects":[]}', 0.1, 0.0
        if "info/refs" in url:
            return 200, b"001e# service=git-upload-pack", 0.1, 0.0
        return 200, b"{}", 0.1, 0.0
    s.tick(cfg, data, now, Gh(), fetch)
    shutil.rmtree(out, ignore_errors=True)
    cfg_path = Path(tempfile.mkdtemp()) / "status.config.json"
    cfg_path.write_text(json.dumps({k: v for k, v in cfg.items() if k not in s.DEFAULTS or k in ("interval_seconds",)} | {"components": cfg["components"]}))
    build_pages.main(["--out", str(out), "--config", str(cfg_path), "--repo", "example/status", "--data-dir", str(data)])
    pages = json.loads((Path(out) / "config.json").read_text())
    pages["data_base"] = ""          # read the files next to the page
    (Path(out) / "config.json").write_text(json.dumps(pages, indent=1))
    return data


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenario", choices=("normal", "outage"), default="normal")
    args = ap.parse_args(argv)
    make(args.out, args.scenario)
    print(f"wrote {args.out} ({args.scenario})")


if __name__ == "__main__":
    sys.exit(main())
