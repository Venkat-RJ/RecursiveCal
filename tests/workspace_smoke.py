"""Foreground browser acceptance checks with temporary, bounded child processes."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recursivecal_lab.inquiry import verify_report


def run(output: Path, browser_path: str | None = None, visual_only: bool = False) -> None:
    from playwright.sync_api import expect, sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    report = {"checks": [], "page_errors": [], "console_errors": []}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    def checked(message: str) -> None:
        report["checks"].append(message)
        print("PASS: " + message, flush=True)

    with (output / "server.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-m", "recursivecal_lab", "serve", "--port", str(port)],
                                  cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(base + "/api/health", timeout=.3):
                        break
                except OSError:
                    if server.poll() is not None:
                        raise RuntimeError("Temporary server exited.")
                    time.sleep(.1)
            else:
                raise RuntimeError("Temporary server did not start.")
            with sync_playwright() as pw:
                options = {"headless": True, "args": ["--use-gl=angle", "--use-angle=swiftshader",
                                                      "--enable-unsafe-swiftshader"]}
                if browser_path:
                    options["executable_path"] = browser_path
                browser = pw.chromium.launch(**options)
                page = browser.new_page(viewport={"width": 1560, "height": 1050}, device_scale_factor=1,
                                        reduced_motion="reduce")
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                page.on("console", lambda message: report["console_errors"].append(message.text)
                        if message.type == "error" else None)
                try:
                    page.goto(base, wait_until="networkidle")
                    expect(page.locator("body")).to_have_attribute("data-loaded", "true", timeout=20000)
                    expect(page.locator("body")).to_have_attribute("data-ready", "connected")
                    expect(page.locator("#runButton")).to_be_enabled()
                    assert not page.locator("#cadUnavailable").is_visible()
                    checked("Local API, verified physics-2 example and articulated CAD load without page errors")

                    def download_current(name: str) -> dict:
                        with page.expect_download() as download:
                            page.locator("#exportButton").click()
                        target = output / name
                        download.value.save_as(target)
                        return json.loads(target.read_text())

                    simulation = download_current("simulation.json")
                    page.locator("#timeline").fill("4200")
                    page.locator("#timeline").dispatch_event("input")
                    expected_t = simulation["trace"][-1]["time_s"] * .42
                    rows = simulation["trace"]
                    before = max((r for r in rows if r["time_s"] <= expected_t), key=lambda r: r["time_s"])
                    after = min((r for r in rows if r["time_s"] >= expected_t), key=lambda r: r["time_s"])
                    weight = (expected_t - before["time_s"]) / (after["time_s"] - before["time_s"]) if after != before else 0
                    expected_q = before["angle_rad"] + (after["angle_rad"] - before["angle_rad"]) * weight
                    assert math.isclose(float(page.locator("#workspace").get_attribute("data-time")), expected_t, abs_tol=1e-9)
                    assert math.isclose(float(page.locator("#rigCanvas").get_attribute("data-angle-rad")), expected_q, abs_tol=1e-9)
                    expected_stroke = before["stroke_m"] + (after["stroke_m"] - before["stroke_m"]) * weight
                    assert math.isclose(float(page.locator("#actuatorSvg").get_attribute("data-stroke-m")), expected_stroke, abs_tol=1e-9)
                    page.locator("#stepForward").click()
                    assert float(page.locator("#workspace").get_attribute("data-time")) > expected_t
                    page.locator("#stepBack").click()
                    page.locator("#playButton").click()
                    expect(page.locator("body")).to_have_attribute("data-playing", "true")
                    page.wait_for_timeout(220)
                    page.screenshot(path=str(output / "simulation-playing.png"), full_page=True)
                    page.locator("#playButton").click()
                    paused = page.locator("#workspace").get_attribute("data-time")
                    page.wait_for_timeout(150)
                    assert page.locator("#workspace").get_attribute("data-time") == paused
                    page.locator("#anglePlot").scroll_into_view_if_needed()
                    click_point = page.locator("#anglePlot").evaluate("""plot => {
                        const point = plot.createSVGPoint(); point.x = 43 + .25*(584-43); point.y = 70;
                        const matrix = plot.getScreenCTM(), client = point.matrixTransform(matrix);
                        return {x:client.x, y:client.y, secondsPerPixel:Number(plot.dataset.duration)/(541*matrix.a)};
                    }""")
                    page.mouse.click(click_point["x"], click_point["y"])
                    # MouseEvent client coordinates quantize to CSS pixels.
                    assert math.isclose(float(page.locator("#workspace").get_attribute("data-time")),
                                        rows[-1]["time_s"]*.25, abs_tol=click_point["secondsPerPixel"])
                    checked("Scrubbing, next/previous samples, pause and plot clicks keep pose, extension and time synchronized")
                    page.locator("#showCutaway").uncheck()
                    assert not page.locator("#actuatorPane").is_visible()
                    page.locator("#showCutaway").check()
                    page.get_by_role("button", name="Right actuator", exact=True).click()
                    expect(page.locator("#actuatorTitle")).to_have_text("Right actuator")
                    page.get_by_role("button", name="Left actuator", exact=True).click()
                    page.locator("#showVectors").check()
                    assert page.locator("#rigOverlay line").count() == 2
                    page.locator("#showTrail").check()
                    page.locator("#timeline").fill("4200")
                    page.locator("#timeline").dispatch_event("input")
                    page.screenshot(path=str(output / "simulation-desktop.png"), full_page=True)
                    page.locator("#focusMechanism").click()
                    expect(page.locator("#focusMechanism")).to_have_attribute("aria-pressed", "true")
                    page.screenshot(path=str(output / "actuator-inspection.png"), full_page=True)
                    page.locator("#resetCamera").click()
                    page.get_by_role("button", name="Gas assistance", exact=True).click()
                    expect(page.locator("#inspector")).to_contain_text("Gas assistance model")
                    page.get_by_role("button", name="Angle sensor", exact=True).click()
                    expect(page.locator("#inspector")).to_contain_text("Encoder bias")
                    page.get_by_role("button", name="Hatch & hinge", exact=True).click()
                    expect(page.locator("#inspector")).to_contain_text("Hinge inertia")
                    page.get_by_role("button", name="Left actuator", exact=True).click()
                    checked("Component inspection, cutaway, camera, force-vector and motion-trail controls work")

                    page.get_by_role("button", name="Investigate", exact=True).click()
                    expect(page.locator("body")).to_have_attribute("data-view", "investigate")
                    assert page.locator("#sideNav .nav-item").count() == 3
                    page.locator("#sideNav .nav-item").nth(1).click()
                    page.locator("#timeline").fill("5000")
                    page.locator("#timeline").dispatch_event("input")
                    assert page.locator("#anglePlot path").count() >= 4
                    assert "delivered force" not in page.locator("#inspector").inner_text().lower()
                    expect(page.locator("#plotsHeading")).to_have_text("Predictions & observations")
                    page.screenshot(path=str(output / "investigation-desktop.png"), full_page=True)
                    recorded = download_current("investigation.json")
                    assert verify_report(recorded)["valid"]
                    selected = recorded["diagnostics"][1]["trace"]
                    selected_t = selected[-1]["time_s"]*.5
                    low = max((r for r in selected if r["time_s"] <= selected_t), key=lambda r:r["time_s"])
                    high = min((r for r in selected if r["time_s"] >= selected_t), key=lambda r:r["time_s"])
                    mix = (selected_t-low["time_s"])/(high["time_s"]-low["time_s"]) if high != low else 0
                    q = low["angle_rad"] + mix*(high["angle_rad"]-low["angle_rad"])
                    assert math.isclose(float(page.locator("#rigCanvas").get_attribute("data-angle-rad")), q, abs_tol=1e-9)
                    checked("Investigation replay uses recorded sensor angles, prior predictions and acquisition samples")

                    page.get_by_role("button", name="Calibrate", exact=True).click()
                    assert page.locator(".parameter-table tbody tr").count() == 5
                    assert "Committed" in page.locator(".parameter-table").inner_text()
                    expect(page.locator("#runState")).to_have_text("Sealed")
                    page.screenshot(path=str(output / "calibration-desktop.png"), full_page=True)
                    page.get_by_role("button", name="Verify", exact=True).click()
                    assert page.locator("#sideNav .nav-item").count() == 4
                    assert page.locator(".check-table tbody tr").count() == 5
                    page.locator("#timeline").fill("5500")
                    page.locator("#timeline").dispatch_event("input")
                    page.screenshot(path=str(output / "verification-desktop.png"), full_page=True)
                    checked("Calibration and verification show sealed values, exact limits and separate unpowered checks")

                    for width in (390, 820, 1560):
                        page.set_viewport_size({"width":width,"height":1050})
                        for view in ("Rig & data", "Investigate", "Calibrate", "Verify"):
                            page.get_by_role("button", name=view, exact=True).click()
                            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), (width,view)
                        if width == 390:
                            page.get_by_role("button", name="Rig & data", exact=True).click()
                            page.screenshot(path=str(output / "simulation-mobile.png"), full_page=True)
                    checked("All four workspaces fit 390, 820 and 1560 pixel viewports without page overflow")
                    if not visual_only:
                        page.get_by_role("button", name="Rig & data", exact=True).click()
                        page.locator("#openSettings").click()
                        page.locator("#scenario").select_option("power_loss")
                        page.locator("#simulationForm .dialog-run").click()
                        expect(page.locator("body")).to_have_attribute("data-busy", "false", timeout=60000)
                        expect(page.locator("#runOrigin")).to_have_text("Computed locally")
                        fresh = download_current("computed-simulation.json")
                        assert fresh["model_id"].endswith("/2")
                        loss = next(e for e in fresh["events"] if e["type"] == "power_loss")
                        page.locator("#inspector").get_by_role("button", name="Power loss", exact=True).click()
                        assert math.isclose(float(page.locator("#workspace").get_attribute("data-time")), loss["time_s"], abs_tol=1e-9)
                        with page.expect_download() as download:
                            page.locator("#exportCsv").click()
                        csv_file=output/"computed-trace.csv";download.value.save_as(csv_file)
                        assert len(csv_file.read_text().splitlines()) == len(fresh["trace"])+1
                        checked("A real new simulation computes, exposes its power-loss event and exports every CSV sample")

                        page.get_by_role("button", name="Investigate", exact=True).click()
                        page.locator("#openSettings").click()
                        page.locator("#condition").select_option("compound")
                        page.locator("#investigationForm .dialog-run").click()
                        expect(page.locator("body")).to_have_attribute("data-busy", "true")
                        page.wait_for_function("""() => document.body.dataset.busy === 'true' && document.body.dataset.study === 'empty' &&
                            document.querySelectorAll('#sideNav .nav-item').length > 0 &&
                            document.querySelectorAll('#anglePlot path').length >= 4""", timeout=60000)
                        page.screenshot(path=str(output / "investigation-computing.png"), full_page=True)
                        expect(page.locator("body")).to_have_attribute("data-busy", "false", timeout=90000)
                        expect(page.locator("#runOrigin")).to_have_text("Computed locally")
                        computed=download_current("computed-investigation.json")
                        assert verify_report(computed)["valid"]
                        assert computed["prediction_history"]
                        assert computed["outcome"] == "verification_failed"
                        page.get_by_role("button", name="Verify", exact=True).click()
                        assert page.locator(".check-table tr.fail").count() >= 1
                        expect(page.locator("#runState")).to_have_text("Failed")
                        page.screenshot(path=str(output/"verification-failed.png"),full_page=True)
                        checked("The real streamed investigation commits once and displays the rejected verification profile")

                        changed=dict(computed);changed["cost"]=0
                        page.locator("#importFile").set_input_files({"name":"changed.json","mimeType":"application/json","buffer":json.dumps(changed).encode()})
                        expect(page.locator("#noticeText")).to_contain_text("integrity check failed")
                        assert page.locator("body").get_attribute("data-study") == "loaded"
                        page.locator("#importFile").set_input_files(output/"investigation.json")
                        expect(page.locator("#runOrigin")).to_have_text("Imported investigation",timeout=20000)
                        restored=download_current("roundtrip-investigation.json")
                        assert restored == recorded
                        checked("Changed evidence is rejected and valid import/export preserves the complete report exactly")

                        page.route("**/api/capabilities",lambda route:route.fulfill(status=200,content_type="application/json",body="{}"))
                        page.reload(wait_until="networkidle")
                        expect(page.locator("body")).to_have_attribute("data-ready","offline")
                        expect(page.locator("body")).to_have_attribute("data-loaded","true",timeout=20000)
                        expect(page.locator("#runButton")).to_be_disabled()
                        assert "Recorded" in page.locator("#runOrigin").inner_text()
                        page.locator("#timeline").fill("3000");page.locator("#timeline").dispatch_event("input")
                        checked("Static mode provides honest recorded replay and never claims to execute a new simulation")

                    assert not report["page_errors"],report["page_errors"]
                    assert not report["console_errors"],report["console_errors"]
                    report["status"]="passed"
                except Exception as error:
                    report["status"] = "failed"
                    report["failure"] = repr(error)
                    page.screenshot(path=str(output / "failure.png"), full_page=True)
                    (output / "failure.html").write_text(page.content())
                    raise
                finally:
                    browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill();server.wait(timeout=5)
            (output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2),flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"artifacts/workspace")
    parser.add_argument("--browser-path")
    parser.add_argument("--visual-only",action="store_true")
    args=parser.parse_args()
    run(args.output,args.browser_path,args.visual_only)
