"""Foreground browser acceptance test; all temporary child processes are closed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recursivecal_lab.inquiry import verify_report


def run(output: Path, browser_path: str | None) -> None:
    from playwright.sync_api import expect, sync_playwright
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    report = {'checks': [], 'page_errors': [], 'console_errors': []}
    with (output / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, '-m', 'recursivecal_lab', 'serve', '--port', str(port)],
                                  cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(base + '/api/health', timeout=.3):
                        break
                except OSError:
                    if server.poll() is not None:
                        raise RuntimeError('temporary test server exited')
                    time.sleep(.1)
            else:
                raise RuntimeError('temporary test server did not start')
            with sync_playwright() as pw:
                options = {'headless': True, 'args': ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']}
                if browser_path:
                    options['executable_path'] = browser_path
                browser = pw.chromium.launch(**options)
                page = browser.new_page(viewport={'width': 1500, 'height': 1100}, device_scale_factor=1)
                page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
                page.on('console', lambda message: report['console_errors'].append(message.text) if message.type == 'error' else None)
                page.goto(base + '/inquiry.html', wait_until='networkidle')
                expect(page.locator('body')).to_have_attribute('data-ready', 'connected')
                expect(page.locator('#runStudy')).to_be_enabled()
                assert not page.locator('#cadFallback').is_visible()
                assert page.locator('#inquiryForm').evaluate('(form) => form.checkValidity()')
                report['checks'].append('Live SI API, valid controls and actual CAD renderer')

                page.locator('#loadRecorded').click()
                expect(page.locator('body')).to_have_attribute('data-report', 'loaded', timeout=15000)
                expect(page.locator('#runKind')).to_contain_text('Recorded evidence')
                expect(page.locator('#message')).to_contain_text('not a new simulation')
                expect(page.locator('#motionResult')).to_have_text('4 / 4 passed')
                assert page.locator('#trajectory path').count() == 3
                assert page.locator('#journal li').count() == 3
                report['checks'].append('Compressed recorded report, browser digest and measured decision history')

                page.locator('#scrubber').fill('730')
                page.locator('#scrubber').dispatch_event('input')
                assert page.locator('#beforeAngle').inner_text() != page.locator('#afterAngle').inner_text()
                page.locator('#cutaway').click()
                expect(page.locator('#cutaway')).to_have_attribute('aria-pressed', 'true')
                page.locator('#cutaway').click()
                page.screenshot(path=str(output / 'inquiry-desktop.png'), full_page=True)
                report['checks'].append('Before/after CAD follows the stored physical traces, with cutaway control')

                with page.expect_download() as download:
                    page.locator('#exportStudy').click()
                saved = output / 'browser-export.json'
                download.value.save_as(saved)
                exported = json.loads(saved.read_text())
                assert verify_report(exported)['valid'], verify_report(exported)
                report['checks'].append('Browser export verifies in Python, including trace-derived tracking metrics')

                page.locator('#case').select_option('compound')
                page.locator('#runStudy').click()
                expect(page.locator('#runStudy')).to_be_enabled(timeout=60000)
                expect(page.locator('#runKind')).to_contain_text('Live simulation')
                expect(page.locator('#motionDetail')).to_have_text('verification failed')
                expect(page.locator('#message')).to_contain_text('independent verification rejected')
                page.locator('#profile').select_option('3')
                page.locator('#scrubber').fill('1000')
                page.locator('#scrubber').dispatch_event('input')
                page.screenshot(path=str(output / 'inquiry-rejected.png'), full_page=True)
                report['checks'].append('Real end-to-end computation and visible rejection of a failed cold profile')

                page.locator('#case').select_option('overload')
                page.locator('#runStudy').click()
                expect(page.locator('#runStudy')).to_be_enabled(timeout=60000)
                expect(page.locator('#modelResult')).to_have_text('Mismatch')
                expect(page.locator('#motionDetail')).to_have_text('abstained')
                expect(page.locator('#commitment')).to_contain_text('Abstained')
                report['checks'].append('Unexplained physical observations cause model mismatch and abstention')

                page.locator('#importStudy').set_input_files(saved)
                expect(page.locator('#runKind')).to_contain_text('Imported report')
                tampered = dict(exported)
                tampered['cost'] = 0
                page.locator('#importStudy').set_input_files({'name': 'changed.json', 'mimeType': 'application/json', 'buffer': json.dumps(tampered).encode()})
                expect(page.locator('#message')).to_contain_text('integrity check failed')
                assert page.evaluate('() => !window.fixtureInjected')
                report['checks'].append('Full report import and rejection of changed evidence')

                page.locator('#importStudy').set_input_files(saved)
                expect(page.locator('#message')).to_contain_text('passed all four independent motion checks')
                page.evaluate('() => { document.activeElement?.blur(); window.scrollTo(0,0); }')

                for width in (390, 820, 1500):
                    page.set_viewport_size({'width': width, 'height': 950})
                    assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth + 1'), width
                    if width == 390:
                        assert 'the machine.' in page.locator('.setup h1').inner_text().replace('\n', ' ')
                        page.screenshot(path=str(output / 'inquiry-mobile.png'), full_page=True)
                report['checks'].append('No horizontal overflow at 390, 820 and 1500 pixels')

                page.route('**/api/inquiry/capabilities', lambda route: route.fulfill(status=200, content_type='application/json', body='{}'))
                page.reload(wait_until='networkidle')
                expect(page.locator('body')).to_have_attribute('data-ready', 'offline')
                expect(page.locator('#runStudy')).to_be_disabled()
                page.locator('#loadRecorded').click()
                expect(page.locator('#motionResult')).to_have_text('4 / 4 passed', timeout=15000)
                expect(page.locator('#runKind')).to_contain_text('Recorded evidence')
                report['checks'].append('Offline mode displays saved evidence and does not pretend to run a simulation')
                assert not report['page_errors'], report['page_errors']
                assert not report['console_errors'], report['console_errors']
                report['status'] = 'passed'
                browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/inquiry-browser')
    parser.add_argument('--browser-path')
    args = parser.parse_args()
    run(args.output, args.browser_path)
