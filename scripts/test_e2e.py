"""python3 -I scripts/test_e2e.py : the whole chain against a local server and a local bare repository."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_pages  # noqa: E402
import monitor  # noqa: E402
import statuslib as s  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/version":
            body, code = b'{"api":"cheesecave"}', 200
        elif self.path == "/":
            body, code = b"<html></html>", 200
        else:
            body, code = b"", 503
        self.send_response(code)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class EndToEnd(unittest.TestCase):
    def test_example_config_is_valid(self):
        cfg = s.load_config(ROOT / "status.config.example.json")
        self.assertTrue(any(c.get("speed") for c in cfg["components"]))

    def test_monitor_publishes_a_branch_that_the_pages_build_can_use(self):
        for key in [k for k in os.environ if k.lower().endswith("_proxy")]:   # a developer's proxy must not see 127.0.0.1
            saved = os.environ.pop(key)
            self.addCleanup(os.environ.__setitem__, key, saved)
        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        tmp = Path(tempfile.mkdtemp())
        cfg_path = tmp / "status.config.json"
        cfg_path.write_text(json.dumps({
            "name": "Local", "base_url": f"http://127.0.0.1:{server.server_port}", "interval_seconds": 1,
            "components": [{"name": "Website", "group": "Web", "path": "/"},
                           {"name": "API", "group": "API", "path": "/api/version", "expect_json": {"api": "cheesecave"}},
                           {"name": "Broken", "group": "API", "path": "/nope"}]}))
        remote = tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)

        code = monitor.main(["--config", str(cfg_path), "--minutes", "0.03", "--data-dir", str(tmp / "data"), "--remote", str(remote)])
        self.assertEqual(code, 0)

        checkout = tmp / "branch"
        self.assertTrue(s.restore(checkout, str(remote)))
        status = json.loads((checkout / "status.json").read_text())
        states = {c["name"]: c["state"] for c in status["components"]}
        self.assertEqual((states["Website"], states["API"]), ("up", "up"))
        self.assertIn(states["Broken"], ("degraded", "down"))
        self.assertEqual([g["name"] for g in status["groups"]], ["Web", "API"])
        self.assertTrue((checkout / "view" / "90d.json").exists())
        self.assertEqual(subprocess.run(["git", "--git-dir", str(remote), "rev-list", "--count", "status"], capture_output=True, text=True).stdout.strip(), "1")

        # a second run continues from the branch instead of starting empty
        monitor.main(["--config", str(cfg_path), "--minutes", "0.01", "--data-dir", str(tmp / "data2"), "--remote", str(remote)])
        again = tmp / "branch2"
        s.restore(again, str(remote))
        lines = sum(len(p.read_text().splitlines()) for p in (again / "checks").glob("*.jsonl"))
        first = sum(len(p.read_text().splitlines()) for p in (checkout / "checks").glob("*.jsonl"))
        self.assertGreater(lines, first)

        out = tmp / "site"
        build_pages.main(["--out", str(out), "--config", str(cfg_path), "--repo", "acme/status", "--data-dir", str(again)])
        pages = json.loads((out / "config.json").read_text())
        self.assertEqual(pages["data_base"], "https://raw.githubusercontent.com/acme/status/status/")
        self.assertTrue((out / "index.html").exists() and (out / "view" / "24h.json").exists())
        empty = tmp / "site2"
        build_pages.main(["--out", str(empty), "--config", str(cfg_path), "--repo", "acme/status"])
        self.assertEqual((empty / "status.json").read_text(), "{}")


if __name__ == "__main__":
    unittest.main()
