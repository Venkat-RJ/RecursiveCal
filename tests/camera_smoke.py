"""Foreground inspection-camera acceptance tests using real browser input.

Loads the same packaged meshes and renderer as the workbench. No server process,
physics recomputation, remote assets, or detached job is needed.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_browser(pw, browser_name: str, output: Path, browser_path: str | None = None) -> dict:
    report = {"browser": browser_name, "checks": [], "skipped": [], "page_errors": [],
              "console_errors": [], "renderers": {}}

    def checked(message: str) -> None:
        report["checks"].append(message)
        print(f"PASS [{browser_name}]: {message}", flush=True)

    options = {"headless": True}
    if browser_name == "chromium":
        options["args"] = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
    if browser_path:
        options["executable_path"] = browser_path
    browser = getattr(pw, browser_name).launch(**options)
    projection_results = []
    try:
        for software in (False, True):
            mode = "software" if software else "preferred"
            context = browser.new_context(viewport={"width": 980, "height": 760},
                                          device_scale_factor=1, has_touch=True)
            page = context.new_page()
            page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
            page.on("console", lambda message: report["console_errors"].append(message.text)
                    if message.type == "error" else None)
            try:
                page.set_content("""<!doctype html><html lang="en"><meta charset="utf-8">
                  <title>RecursiveCal inspection camera</title>
                  <style>body{margin:16px;background:#f6f5ef;font:14px system-ui;color:#253139}
                  canvas{display:block;width:min(900px,calc(100vw - 32px));height:550px;
                  max-height:65vh;margin:10px 0;outline-offset:3px}canvas:focus{outline:2px solid #ce6b28}
                  button{padding:6px 12px}p{max-width:900px}</style>
                  <h1>Inspection camera</h1><button>Before camera</button>
                  <canvas id="camera" tabindex="0" aria-label="Interactive liftgate inspection camera"
                    aria-describedby="cameraHelp"></canvas><button>After camera</button>
                  <p id="cameraHelp">Drag to orbit. Shift-drag to pan. Scroll or pinch to zoom.
                  Arrow keys orbit; Shift and arrows pan. Plus and minus zoom. Home resets.
                  Keys 1 to 4 select isometric, front, side and top views.</p></html>""")
                for filename in ("inquiry-geometry.js", "inquiry-cad.js", "inquiry-renderer.js"):
                    page.add_script_tag(path=str(ROOT / "recursivecal_lab/web" / filename))
                page.evaluate("""software => {
                    window.camera = new PhysicalRenderer(document.querySelector('#camera'),
                        {theme:'light',software});
                    camera.draw(.47);
                }""", software)
                canvas = page.locator("#camera")
                actual = page.evaluate("camera.software ? 'software' : 'webgl2'")
                report["renderers"][mode] = actual
                if software:
                    assert actual == "software"
                elif browser_name == "chromium":
                    assert actual == "webgl2", "Chromium must exercise the WebGL path in this gate."
                initial = page.evaluate("camera.getCamera()")
                bounds = canvas.bounding_box()
                assert bounds
                cx, cy = bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2

                # Native mouse events exercise pointer capture and gesture completion.
                page.mouse.move(cx, cy)
                page.mouse.down()
                page.mouse.move(cx + 60, cy + 30, steps=6)
                page.mouse.up()
                orbit = page.evaluate("camera.getCamera()")
                assert orbit["yaw_rad"] > initial["yaw_rad"] + .2
                assert orbit["elevation_rad"] > initial["elevation_rad"] + .05
                assert page.evaluate("camera.pointers.size") == 0
                assert page.evaluate("camera.gesture === null")
                old_radius = orbit["distance_m"]
                page.mouse.wheel(0, 250)
                page.wait_for_function("distance => camera.radius > distance", arg=old_radius)
                assert page.evaluate("camera.radius") <= 11
                checked(f"{mode}: native orbit, wheel zoom and pointer release")

                old_target = page.evaluate("camera.getCamera().target_m")
                page.keyboard.down("Shift")
                try:
                    page.mouse.move(cx, cy)
                    page.mouse.down()
                    page.mouse.move(cx + 40, cy - 20, steps=5)
                    page.mouse.up()
                finally:
                    page.keyboard.up("Shift")
                new_target = page.evaluate("camera.getCamera().target_m")
                assert math.dist(old_target, new_target) > .03
                page.keyboard.press("Home")
                assert page.evaluate("camera.getCamera()") == initial

                # The canvas is keyboard reachable and does not trap focus.
                page.get_by_role("button", name="Before camera", exact=True).focus()
                page.keyboard.press("Tab")
                assert canvas.evaluate("c => c === document.activeElement")
                page.keyboard.press("ArrowRight")
                assert page.evaluate("camera.yaw") > initial["yaw_rad"]
                page.keyboard.press("Equal")
                assert page.evaluate("camera.radius") < initial["distance_m"]
                page.keyboard.press("Home")
                assert page.evaluate("camera.getCamera()") == initial
                page.keyboard.press("Tab")
                assert page.get_by_role("button", name="After camera", exact=True).evaluate(
                    "b => b === document.activeElement")
                checked(f"{mode}: Shift-drag pan, keyboard access, zoom and reset")

                canvas.focus()
                for key, name in (("2", "front"), ("3", "side"), ("4", "top"), ("1", "isometric")):
                    page.keyboard.press(key)
                    assert page.evaluate("camera.getView()") == name
                    point = page.evaluate("camera.projectPoint(camera.target)")
                    assert math.isclose(point["x"], bounds["width"] / 2, abs_tol=1e-6)
                    assert math.isclose(point["y"], bounds["height"] / 2, abs_tol=1e-6)
                page.evaluate("camera.setFocus('mechanism'); camera.setView('side')")
                page.keyboard.press("Home")
                assert page.evaluate("camera.mechanics")
                assert page.evaluate("camera.getView()") == "isometric"
                page.evaluate("camera.setFocus('assembly')")
                checked(f"{mode}: all presets project the target centrally and reset preserves focus")

                imported = page.evaluate("""() => {
                    const state=JSON.parse(JSON.stringify(camera.getCamera()));
                    camera.setView('top');camera.setCamera(state);
                    const before=JSON.stringify(camera.getCamera());
                    let rejected=false;
                    try {camera.setCamera({...state,distance_m:Infinity});} catch {rejected=true;}
                    return {same:before===JSON.stringify(camera.getCamera()),rejected};
                }""")
                assert imported == {"same": True, "rejected": True}
                assert page.evaluate("camera.q") == .47
                checked(f"{mode}: camera round trip and rejected import preserve physical pose")

                # CDP sends native multitouch input, not synthetic DOM pointer events.
                if browser_name == "chromium":
                    client = context.new_cdp_session(page)
                    for event, separation in (("touchStart", 100), ("touchMove", 200)):
                        client.send("Input.dispatchTouchEvent", {
                            "type": event,
                            "touchPoints": [{"x": cx - separation / 2, "y": cy, "id": 11},
                                            {"x": cx + separation / 2, "y": cy, "id": 12}],
                        })
                    client.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                    page.wait_for_function("camera.pointers.size === 0")
                    pinch = page.evaluate("camera.getCamera()")
                    assert math.isclose(pinch["distance_m"], initial["distance_m"] / 2, abs_tol=.02)
                    assert math.dist(pinch["target_m"], initial["target_m"]) < 1e-6
                    assert page.evaluate("camera.gesture === null")
                    client.detach()
                    checked(f"{mode}: native two-touch pinch zoom and complete release")
                else:
                    report["skipped"].append(f"{mode}: native multitouch injection unavailable through Playwright WebKit; Chromium covers pinch")

                page.evaluate("camera.resetCamera()")
                projection_results.append(page.evaluate("""() => ({state:camera.getCamera(),
                    points:[[0,0,1.76],[.2,.5,1.2],[-.47,-.46,1.17]].map(p=>camera.projectPoint(p))})"""))
                visible = page.evaluate("""() => {
                    const {width,height}=camera.canvas;
                    let data;
                    if(camera.software)data=camera.ctx.getImageData(0,0,width,height).data;
                    else {data=new Uint8Array(width*height*4);camera.gl.readPixels(0,0,width,height,
                        camera.gl.RGBA,camera.gl.UNSIGNED_BYTE,data);}
                    const colors=new Set();
                    for(let i=0;i<data.length;i+=4*89)colors.add(`${data[i]},${data[i+1]},${data[i+2]}`);
                    return colors.size;
                }""")
                assert visible > 8, f"Expected rendered mechanism, found {visible} colors"
                if not software:
                    canvas.screenshot(path=str(output / f"camera-{browser_name}.png"))
                page.set_viewport_size({"width":390,"height":720})
                page.wait_for_function("camera.canvas.width <= 390")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.evaluate("camera.getCamera()") == initial
                assert not report["page_errors"], report["page_errors"]
                assert not report["console_errors"], report["console_errors"]
                checked(f"{mode}: actual mesh render and narrow viewport preserve camera state")
            finally:
                context.close()
        assert projection_results[0] == projection_results[1]
        checked("Preferred and software rendering use the same camera and projection")
        report["status"] = "passed"
        return report
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        (output / f"report-{browser_name}.json").write_text(json.dumps(report, indent=2) + "\n")
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/camera-browser"))
    parser.add_argument("--browser", choices=("chromium", "webkit"), default="chromium")
    parser.add_argument("--all", action="store_true", help="Run both Chromium and WebKit")
    parser.add_argument("--browser-path")
    args = parser.parse_args()
    if args.all and args.browser_path:
        parser.error("--browser-path selects one engine and cannot be combined with --all")
    args.output.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    report = {"scope":"Inspection-camera controls and rendering; not camera-sensor calibration", "browsers":[]}
    try:
        with sync_playwright() as pw:
            for name in (("chromium", "webkit") if args.all else (args.browser,)):
                report["browsers"].append(run_browser(pw, name, args.output, args.browser_path))
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
