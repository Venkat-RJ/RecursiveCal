"""Exercise actual CLI and HTTP boundaries, including untrusted local inputs."""
from __future__ import annotations

import gzip
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from recursivecal_lab.api import capabilities, dispatch
from recursivecal_lab.io import loads, read_json, write_json
from recursivecal_lab.inquiry import verify_report
from recursivecal_lab.server import Handler, WorkbenchServer


class InputTests(unittest.TestCase):
    def test_gzip_reports_round_trip_and_preserve_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = {"trace": [0.1, 0.2], "outcome": "rejected"}
            plain = write_json(root / "report.json", value)
            packed = write_json(root / "report.json.gz", value)
            second = write_json(root / "other-name.json.gz", value)
            self.assertEqual(gzip.decompress(packed.read_bytes()), plain.read_bytes())
            self.assertEqual(read_json(packed), value)
            self.assertEqual(packed.read_bytes(), second.read_bytes())
            with self.assertRaises(FileExistsError):
                write_json(packed, {"changed": True})
            self.assertEqual(read_json(packed), value)

    def test_gzip_reports_bound_decompressed_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.json.gz"
            path.write_bytes(gzip.compress(b'{"x":"' + b'a' * 4096 + b'"}'))
            self.assertLess(path.stat().st_size, 128)
            with self.assertRaisesRegex(ValueError, "decompressed JSON input"):
                read_json(path, max_bytes=128)

    def test_gzip_reports_reject_corruption_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json.gz"
            for raw in (b'not gzip', gzip.compress(b'{}')[:-3],
                        gzip.compress(b'{"x":1,"x":2}'), gzip.compress(b'{"x":NaN}')):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    read_json(path)

    def test_nonfinite_duplicate_and_unknown_inputs_rejected(self):
        for text in ('{"mass":NaN}', '{"x":1,"x":2}', '{"mass":Infinity}'):
            with self.assertRaises(ValueError):
                loads(text)
        with self.assertRaises(ValueError):
            dispatch("/api/simulate", {"parameters": {"mass_kg": True}})
        with self.assertRaises(ValueError):
            dispatch("/api/simulate", {"duration": 5})
        with self.assertRaises(ValueError):
            dispatch("/api/simulate", {"duration_s": 120, "dt_s": 0.0001})

    def test_atomic_outputs_preserve_previous_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_json(path, {"value": 1})
            with self.assertRaises(FileExistsError):
                write_json(path, {"value": 2})
            self.assertEqual(json.loads(path.read_text()), {"value": 1})
            with self.assertRaises(ValueError):
                write_json(path, {"value": float("nan")}, overwrite=True)
            self.assertEqual(json.loads(path.read_text()), {"value": 1})
            write_json(path, {"value": 3}, overwrite=True)
            self.assertEqual(json.loads(path.read_text()), {"value": 3})

    def test_capabilities_are_json_serializable_and_explicit(self):
        cap = capabilities()
        json.dumps(cap, allow_nan=False)
        self.assertFalse(cap["hardware_connected"])
        self.assertFalse(cap["passive_hold"]["can_hold_open_without_motor"])
        self.assertIn("mass_kg", cap["default_parameters"])


class CLITests(unittest.TestCase):
    def cli(self, directory, *arguments):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        return subprocess.run([sys.executable, "-m", "recursivecal_lab", *arguments],
                              cwd=directory, env=env, capture_output=True, text=True, timeout=30)

    def test_installed_style_entry_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.cli(directory, "doctor")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "ok")
            result = self.cli(directory, "simulate", "--duration", "0.55", "--dt", "0.02",
                              "--output", "run.json", "--csv", "trace.csv")
            self.assertEqual(result.returncode, 0, result.stderr)
            run = json.loads((Path(directory) / "run.json").read_text())
            self.assertAlmostEqual(run["trace"][-1]["time_s"], 0.55)
            self.assertTrue((Path(directory) / "trace.csv").is_file())
            repeat = self.cli(directory, "simulate", "--output", "run.json")
            self.assertEqual(repeat.returncode, 2)
            self.assertIn("exists", repeat.stderr)

    def test_invalid_simulation_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.cli(directory, "simulate", "--dt", "nan", "--output", "bad.json")
            self.assertEqual(result.returncode, 2)
            self.assertFalse((Path(directory) / "bad.json").exists())


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = WorkbenchServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.worker = threading.Thread(target=cls.server.serve_forever)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=5)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            result = connection.getresponse()
            return result.status, dict(result.getheaders()), result.read()
        finally:
            connection.close()

    def test_roundtrip_and_assets(self):
        status, headers, html = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"RecursiveCal", html)
        self.assertIn("Content-Security-Policy", headers)
        status, _, raw = self.request("POST", "/api/simulate", '{"duration_s":0.1}', {"Content-Type": "application/json"})
        self.assertEqual(status, 200, raw)
        self.assertAlmostEqual(json.loads(raw)["trace"][-1]["time_s"], 0.1)

    def test_untrusted_origin_host_path_and_json(self):
        status, _, _ = self.request("GET", "/api/health", headers={"Host": "attacker.invalid"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/api/simulate", '{}',
                                   {"Content-Type": "application/json", "Origin": "https://attacker.invalid"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("GET", "/%2e%2e/pyproject.toml")
        self.assertEqual(status, 404)
        for body in ('{"duration_s":NaN}', '{"dt_s":0.01,"dt_s":0.02}', '{"parameters":{"unknown":1}}'):
            status, _, raw = self.request("POST", "/api/simulate", body, {"Content-Type": "application/json"})
            self.assertEqual(status, 400, raw)
        status, _, _ = self.request("POST", "/api/simulate", '{}', {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)

    def test_investigation_stream_and_input_boundary(self):
        headers = {"Content-Type": "application/json"}
        for body in ('[]', '{"unknown":1}', '{"case":"missing"}', '{"seed":true}'):
            status, _, raw = self.request("POST", "/api/inquiry/stream", body, headers)
            self.assertEqual(status, 400, raw)
        status, response_headers, raw = self.request(
            "POST", "/api/inquiry/stream", '{"policy":"no_probe"}', headers)
        self.assertEqual(status, 200, raw)
        self.assertIn("application/x-ndjson", response_headers["Content-Type"])
        events = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual([event["type"] for event in events], ["started", "committed", "complete"])
        self.assertNotIn("evaluator_only_truth", json.dumps(events[:-1]))
        self.assertTrue(verify_report(events[-1]["report"])["valid"])


if __name__ == "__main__":
    unittest.main()

