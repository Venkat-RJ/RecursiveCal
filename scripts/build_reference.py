"""Bundle actual release artifacts for recorded-only browser inspection."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
inputs = {"run": "research/releases/physical-v1/open_run.json", "experiment": "research/releases/v0.3/summary.json"}
bundle = {key: json.loads((ROOT / path).read_text()) for key, path in inputs.items()}
bundle["sources"] = {key: {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
                     for key, path in inputs.items()}
target = ROOT / "recursivecal_lab/web/reference-data.js"
target.write_text('"use strict";\nwindow.RecursiveCalReference = ' + json.dumps(bundle, separators=(",", ":"), allow_nan=False) + ";\n")
print(f"Bundled {len(bundle['run']['trace'])} recorded samples and {len(bundle['experiment']['results'])} benchmark cohorts: {target}")

