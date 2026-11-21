"""End-to-end workbench checks against the real local API.

Run in the foreground: python tests/workbench_smoke.py
Install the browser first in CI: python -m playwright install --with-deps chromium
The managed server is terminated in finally. No server or browser is left running.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def run(browser_path: str | None, output: Path) -> None:
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = (output / "server.log").open("w")
    process = subprocess.Popen([sys.executable, "-m", "recursivecal_lab", "serve", "--port", str(port)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    report = {"checks": [], "console_errors": [], "expected_api_errors": [], "page_errors": []}
    expected_invalid_fit = False
    browser = None
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Workbench server exited: " + (output / "server.log").read_text())
            try:
                with urllib.request.urlopen(base + "/api/capabilities", timeout=0.3) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Local workbench did not become ready")

        with sync_playwright() as playwright:
            launch = {"headless": True}
            if browser_path:
                launch["executable_path"] = browser_path
            browser = playwright.chromium.launch(**launch)
            page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
            page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
            def record_console(message):
                if message.type != "error":
                    return
                if expected_invalid_fit and message.location.get("url", "").endswith("/api/fit-force") and "400" in message.text:
                    report["expected_api_errors"].append(message.text)
                else:
                    report["console_errors"].append(message.text)
            page.on("console", record_console)
            page.goto(base, wait_until="networkidle")
            page.wait_for_function("document.body.dataset.ready === 'connected'")
            assert page.locator("#runButton").is_enabled()
            assert page.locator("#exportRun").is_disabled()
            assert page.evaluate("document.getElementById('simulationForm').checkValidity()")
            report["checks"].append("Live API and valid initial configuration")

            page.locator("#runButton").click()
            page.wait_for_function("document.getElementById('runStatus').textContent === 'Completed'")
            assert page.locator("#anglePlot path").count() >= 2
            assert "insufficient holding capacity" in page.locator("#holdSummary").inner_text()
            assert "n/a" not in page.locator("#metricRmse").inner_text()
            page.screenshot(path=str(output / "simulation_desktop.png"), full_page=True)
            report["checks"].append("Real simulation, plots, metrics and passive-hold deficit")

            with page.expect_download() as download_info:
                page.locator("#exportRun").click()
            run_path = output / "run.json"
            download_info.value.save_as(run_path)
            saved_run = json.loads(run_path.read_text())
            assert saved_run["schema_version"] == "recursivecal.run/1"
            with page.expect_download() as download_info:
                page.locator("#exportTrace").click()
            trace_path = output / "trace.csv"
            download_info.value.save_as(trace_path)
            rows = list(csv.DictReader(io.StringIO(trace_path.read_text())))
            assert len(rows) == len(saved_run["trace"])
            report["checks"].append("JSON and CSV downloads preserve actual trace sample count")

            page.locator("#pinRun").click()
            page.locator("#mass").fill("30")
            page.locator("#runButton").click()
            page.wait_for_function("!document.getElementById('runButton').disabled")
            assert page.locator("#compareLegend").is_visible()
            assert page.locator("#anglePlot path").count() == 3
            report["checks"].append("Pinned-run overlay after a changed plant")

            page.locator("#resetConfig").click()
            page.locator("#scenario").select_option("passive_hold")
            page.locator("#runButton").click()
            page.wait_for_function("!document.getElementById('runButton').disabled")
            assert "aborted" in page.locator("#runStatus").inner_text().lower()
            assert "Simulation stopped" in page.locator("#globalMessage").inner_text()
            assert "Speed Limit" in page.locator("#events").inner_text()
            report["checks"].append("Early termination remains visible as a stopped simulation")

            page.locator("#importRun").set_input_files(run_path)
            page.wait_for_function("document.getElementById('runStatus').textContent === 'Completed'")
            page.locator("[data-view='measurements']").click()
            page.locator("#forceExample").click()
            assert page.locator("#forceKind").input_value() == "synthetic"
            page.locator("#fitButton").click()
            page.locator("#forceResults").wait_for(state="visible")
            fit = json.loads(page.locator("#forceJson").inner_text())
            assert "synthetic" in json.dumps(fit)
            assert "validation" in json.dumps(fit)
            report["checks"].append("Actual force fitting with separate validation data and synthetic provenance")

            assert page.locator("#applyFit").is_enabled()
            page.locator("#applyFit").click()
            page.locator("#view-simulation").wait_for(state="visible")
            assert "Fitted curve applied" in page.locator("#globalMessage").inner_text()
            page.locator("#runButton").click()
            page.wait_for_function("!document.getElementById('runButton').disabled")
            provenance = json.loads(page.locator("#runProvenance").inner_text())["provenance"]
            assert provenance["source_kind"] == "synthetic"
            assert provenance["parameter_provenance"]["source_kind"] == "synthetic"
            report["checks"].append("Applying a fitted curve retains its provenance in a new synthetic run")
            page.locator("#importRun").set_input_files(run_path)
            page.wait_for_function("document.getElementById('runIdentity').textContent.includes('Imported')")
            page.locator("[data-view='measurements']").click()

            page.locator("#replayCsv").fill("time_s,angle_rad\n" + "\n".join(f"{row['time_s']},{row['angle_rad']}" for row in saved_run["trace"][::10]))
            page.locator("#replayKind").select_option("synthetic")
            page.locator("#replaySource").fill("Smoke test: downsampled simulator trace")
            page.locator("#replayButton").click()
            page.locator("#replayResults").wait_for(state="visible")
            replay = json.loads(page.locator("#replayJson").inner_text())
            assert "synthetic" in json.dumps(replay)
            page.screenshot(path=str(output / "measurements_desktop.png"), full_page=True)
            report["checks"].append("Actual trajectory comparison of explicitly synthetic samples")

            page.locator("#forceCsv").fill("length_m,force_N_each,split\n0.4,200,train\n")
            expected_invalid_fit = True
            page.locator("#fitButton").click()
            page.wait_for_function("document.getElementById('forceMessage').classList.contains('error')")
            assert not page.locator("#forceResults").is_visible()
            report["checks"].append("Invalid measurement errors are visible without a stale fit result")

            fixture = {"schema_version": "recursivecal.experiment.v1", "model_id": "recursivecal-normalized-v0.2", "scope": "Synthetic smoke-test fixture, not research evidence", "seeds": [13], "results": {"fixture": {"n": 2, "policies": {"fixed": {"mean_reward": 0.8, "mean_quality": 0.812, "mean_cost": 1, "mean_probes": 1, "n": 2}}, "paired_comparisons": {"fixed minus no_probe": {"mean_difference": 0.01, "ci95": [-0.01, 0.03]}}}}}
            page.locator("[data-view='evidence']").click()
            page.locator("#importEvidence").set_input_files({"name": "fixture.json", "mimeType": "application/json", "buffer": json.dumps(fixture).encode()})
            page.locator("#evidenceContent").wait_for(state="visible")
            assert "0.800000" in page.locator("#evidenceTables").inner_text()
            assert "[-0.010000, 0.030000]" in page.locator("#evidenceTables").inner_text()
            page.screenshot(path=str(output / "evidence_desktop.png"), full_page=True)
            report["checks"].append("Experiment import displays recorded means and paired confidence intervals")

            for width in (390, 820, 1440):
                page.set_viewport_size({"width": width, "height": 950})
                for view in ("simulation", "measurements", "evidence"):
                    page.locator(f"[data-view='{view}']").click()
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), (width, view)
                if width == 390:
                    page.locator("[data-view='simulation']").click()
                    page.screenshot(path=str(output / "simulation_mobile.png"), full_page=True)
            report["checks"].append("No horizontal overflow at 390, 820 and 1440 pixels in all views")

            page.locator("[data-view='simulation']").click()
            hostile = json.loads(run_path.read_text())
            hostile["provenance"]["source"] = '<img src=x onerror="window.fixtureInjected=true">'
            page.locator("#importRun").set_input_files({"name": "untrusted.json", "mimeType": "application/json", "buffer": json.dumps(hostile).encode()})
            page.wait_for_function("document.getElementById('runProvenance').textContent.includes('fixtureInjected')")
            assert page.locator("img[src='x']").count() == 0
            assert page.evaluate("window.fixtureInjected === undefined")
            report["checks"].append("Imported provenance is text, never executable HTML")

            await_route = lambda route: route.fulfill(status=200, content_type="application/json", body='{"error":"API unavailable for import-only test"}')
            page.route("**/api/capabilities", await_route)
            page.reload(wait_until="networkidle")
            page.wait_for_function("document.body.dataset.ready === 'offline'")
            assert page.locator("#runButton").is_disabled()
            page.locator("#importRun").set_input_files(run_path)
            page.wait_for_function("!document.getElementById('exportRun').disabled")
            assert page.locator("#anglePlot path").count() >= 2
            report["checks"].append("Import-only mode works without the computation API")
            assert page.locator("#loadReferenceRun").is_enabled()
            page.locator("#loadReferenceRun").click()
            assert "Recorded" in page.locator("#runStatus").inner_text()
            assert "saved results, not a new simulation" in page.locator("#globalMessage").inner_text()
            assert page.locator("#runButton").is_disabled()
            page.locator("[data-view='evidence']").click()
            page.locator("#loadReferenceEvidence").click()
            assert page.locator("#evidenceTitle").inner_text() == "Recorded release benchmark"
            assert page.locator("#evidenceTables table").count() > 0
            report["checks"].append("Recorded release examples remain explicitly labelled without a live API")

            assert not report["page_errors"], report["page_errors"]
            assert not report["console_errors"], report["console_errors"]
            report["status"] = "passed"
            print(json.dumps(report, indent=2), flush=True)
            browser.close()
            browser = None
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser-path")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "workbench")
    arguments = parser.parse_args()
    run(arguments.browser_path, arguments.output)
