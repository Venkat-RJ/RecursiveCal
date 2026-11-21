"""Optional browser smoke test for the generated RecursiveCal CAD viewer.

From mechanics/cad_v1:
  python -m pip install playwright
  python -m playwright install chromium
  python viewer/build.py
  python tests/browser_smoke.py
"""
import asyncio
import shutil
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]

async def run():
    html = ROOT / "viewer" / "RecursiveCal_CAD_Lab.html"
    if not html.exists():
        raise FileNotFoundError("Run python viewer/build.py first")
    async with async_playwright() as p:
        binary = shutil.which("chromium") or shutil.which("google-chrome")
        opts = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if binary:
            opts["executable_path"] = binary
        browser = await p.chromium.launch(**opts)
        page = await browser.new_page(viewport={"width": 1530, "height": 1000})
        errors = []
        page.on("pageerror", lambda x: errors.append(str(x)))
        await page.set_content(html.read_text(), wait_until="load", timeout=100000)
        await page.wait_for_function("window.__recursivecal && window.__recursivecal.state.factoryRun", timeout=60000)
        stats = await page.evaluate("""() => ({
            parts: window.__recursivecal.scene.parts.length,
            frames: window.__recursivecal.state.factoryRun.frames.length
        })""")
        assert stats["parts"] >= 50 and stats["frames"] >= 100, stats
        await page.locator("#suggestBtn").click()
        await page.locator("#compareBtn").click()
        await page.locator("#scrubber").evaluate("""el => {
            el.value = "4.2";
            el.dispatchEvent(new Event("input", {bubbles:true}));
        }""")
        metrics = await page.evaluate("""() => ({
            enabled: window.__recursivecal.state.compare,
            factory: window.__recursivecal.state.factoryRun.metrics.final_angle_deg,
            modified: window.__recursivecal.state.tunedRun.metrics.final_angle_deg
        })""")
        assert metrics["enabled"] and metrics["factory"] < metrics["modified"], metrics
        await page.locator("#viewMech").click()
        await page.locator("#viewVehicle").click()
        await page.locator("#faultSelect").select_option("gas_leak")
        await page.set_viewport_size({"width":390,"height":844})
        overflow = await page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth+2")
        assert not overflow, "mobile horizontal overflow"
        assert not errors, errors
        print("Browser smoke PASS:", stats, metrics, "JavaScript errors:", len(errors))
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
