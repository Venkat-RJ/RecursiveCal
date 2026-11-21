"""Build a deterministic, synthetic physics-2 example for the static workspace."""
from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recursivecal_lab.inquiry import run_study, verify_report
from recursivecal_lab.physics import simulate


def main() -> None:
    simulation = simulate()
    report = run_study(case="weak_motor", seed=7, progress=lambda message: print(message, flush=True))
    check = verify_report(report)
    if not check["valid"]:
        raise ValueError(check)
    payload = json.dumps({"simulation": simulation, "investigation": report},
                         separators=(",", ":"), allow_nan=False).encode()
    encoded = base64.b64encode(gzip.compress(payload, mtime=0)).decode()
    target = ROOT / "recursivecal_lab/web/workspace-reference.js"
    target.write_text('/* Recorded synthetic physics-2 evidence. Regenerate with scripts/build_workspace_reference.py. */\n'
                      '"use strict";\nwindow.RecursiveWorkspaceReference = "' + encoded + '";\n')
    print(json.dumps({"target": str(target), "simulation_samples": len(simulation["trace"]),
                      "diagnostic_tests": len(report["agent_history"]), "outcome": report["outcome"],
                      "report_sha256": report["report_sha256"], "compressed_bytes": len(encoded)}, indent=2))


if __name__ == "__main__":
    main()
