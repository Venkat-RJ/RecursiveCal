"""Verify local documentation, frozen source, and bundled evidence consistency."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--archive", type=Path, help="also verify the built source distribution")
args = parser.parse_args()
errors = []
for name, expected in {"recursivecal.py": "2d939005aaa177ba8d9f4d2296db0577c6bb3111",
                       "mechanics/cad_v1/simulation/physics_v2.py": "fb6f903631a036d2f0d6e7ec1a3f556a7a3a10cc"}.items():
    raw = (ROOT / name).read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != expected:
        errors.append(f"frozen model changed: {name}")
project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
from recursivecal_lab import __version__
if project["version"] != __version__:
    errors.append("package and runtime versions disagree")
citation = (ROOT / "CITATION.cff").read_text()
citation_version = re.search(r'^version:\s*[\"\']?([^\"\'\s]+)', citation, re.MULTILINE)
if citation_version is None or citation_version.group(1) != __version__:
    errors.append("citation and package versions disagree")
bibtex = (ROOT / "CITATION.bib").read_text()
if f"version = {{{__version__}}}" not in bibtex:
    errors.append("BibTeX and package versions disagree")
readme = (ROOT / "README.md").read_text()
if bibtex.split("@software", 1)[1].strip() not in readme:
    errors.append("README citation differs from CITATION.bib")
for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), ROOT / "paper/README.md"]:
    if not path.is_file():
        errors.append(f"missing document: {path.relative_to(ROOT)}")
        continue
    for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        target = target.split("#", 1)[0].split("?", 1)[0]
        if target and not (path.parent / target).exists():
            errors.append(f"broken local link: {path.relative_to(ROOT)} -> {target}")
asset = (ROOT / "recursivecal_lab/web/reference-data.js").read_text()
prefix = '"use strict";\nwindow.RecursiveCalReference = '
if not asset.startswith(prefix) or not asset.endswith(";\n"):
    errors.append("unexpected recorded-data wrapper")
else:
    bundle = json.loads(asset[len(prefix):-2])
    for key, item in bundle["sources"].items():
        raw = (ROOT / item["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"] or bundle[key] != json.loads(raw):
            errors.append(f"recorded workbench data drifted: {key}")
audit = json.loads((ROOT / "research/releases/physical-v1/audit.json").read_text())
historical = json.loads((ROOT / "research/releases/physics-v2/historical-evidence.json").read_text())
if historical['source_commit'] != '8d51692799b1eaffb18c3f91def12fac44a1b8af':
    errors.append('historical physics source revision changed')
if audit["provenance"]["model_source_sha256"] != historical['historical_source_sha256']['physics.py']:
    errors.append("historical physical audit differs from its pinned source")
for name, expected in historical['historical_artifacts_sha256'].items():
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
        errors.append(f"historical physics evidence changed: {name}")
validation = json.loads((ROOT / 'research/releases/physics-v2/validation.json').read_text())
from recursivecal_lab.physics import MODEL_ID
if validation['model_id'] != MODEL_ID or not validation['passed'] or not all(validation['gates'].values()):
    errors.append('current physics numerical validation does not pass for this model')
for name, expected in validation['source_sha256'].items():
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
        errors.append(f'current physics validation source drifted: {name}')
from recursivecal_lab.io import MAX_REPORT_BYTES, read_json
from scripts.package_rig_evidence import full_report_metadata, validation_summary
evidence_root = ROOT / 'research/releases/research-rig-v3'
research_validation = read_json(evidence_root / 'validation.json.gz', max_bytes=MAX_REPORT_BYTES)
with gzip.open(evidence_root / 'validation.json.gz', 'rb') as handle:
    research_validation_raw = handle.read(MAX_REPORT_BYTES + 1)
research_validation_gzip = (evidence_root / 'validation.json.gz').read_bytes()
if read_json(evidence_root / 'validation.json') != validation_summary(
        research_validation, full_report_metadata(research_validation_raw, research_validation_gzip)):
    errors.append('research rig summary differs from complete compressed evidence')
from recursivecal_lab.research_rig import MODEL_ID as RESEARCH_MODEL_ID
if (research_validation['model_id'] != RESEARCH_MODEL_ID or not research_validation['passed']
        or not all(research_validation['gates'].values())):
    errors.append('research rig numerical validation does not pass for this model')
if research_validation['source_sha256'] != research_validation['source_sha256_after_audit']:
    errors.append('research rig source changed during the recorded audit')
for name, expected in research_validation['source_sha256'].items():
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
        errors.append(f'research rig validation source drifted: {name}')
from recursivecal_lab.rl_environment import verify_episode_report
rl_smoke = read_json(evidence_root / 'rl-smoke.json.gz', max_bytes=MAX_REPORT_BYTES)
if not verify_episode_report(rl_smoke)['valid']:
    errors.append('recorded physical RL smoke episode failed integrity or protocol checks')
for name, expected in rl_smoke['source_sha256'].items():
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
        errors.append(f'physical RL smoke source drifted: {name}')
if (ROOT / "docs/EXPERIMENT_PROTOCOL.md").read_bytes() != (ROOT / "recursivecal_lab/data/EXPERIMENT_PROTOCOL.md").read_bytes():
    errors.append("installed experiment protocol differs from documentation")
from recursivecal_lab.inquiry import verify_report
recorded_asset = (ROOT / "recursivecal_lab/web/inquiry-reference.js").read_text()
match = re.search(r'window\.RecursiveCalInquiryReferenceGzip = "([A-Za-z0-9+/=]+)";', recorded_asset)
if not match:
    errors.append("physical inquiry recorded report is missing")
else:
    inquiry_report = json.loads(gzip.decompress(base64.b64decode(match.group(1))))
    if not verify_report(inquiry_report)["valid"]:
        errors.append("physical inquiry recorded report failed integrity or protocol checks")
    for name, expected in inquiry_report["provenance"]["source_sha256"].items():
        if historical['historical_source_sha256'].get(name) != expected:
            errors.append(f"historical inquiry recorded source drifted: {name}")
workspace_asset = (ROOT / "recursivecal_lab/web/workspace-reference.js").read_text()
workspace_match = re.search(r'window\.RecursiveWorkspaceReference = "([A-Za-z0-9+/=]+)";', workspace_asset)
if not workspace_match:
    errors.append("current workspace recorded evidence is missing")
else:
    workspace = json.loads(gzip.decompress(base64.b64decode(workspace_match.group(1))))
    if workspace['simulation']['model_id'] != 'recursivecal.si-liftgate/3':
        errors.append('current workspace simulation must use research rig 3')
    if (workspace['investigation']['model_id'] != RESEARCH_MODEL_ID
            or not verify_report(workspace['investigation'])['valid']):
        errors.append('current workspace investigation is invalid or uses an older rig')
    for kind in ('simulation', 'investigation'):
        for name, expected in workspace[kind]['provenance']['source_sha256'].items():
            if hashlib.sha256((ROOT / 'recursivecal_lab' / name).read_bytes()).hexdigest() != expected:
                errors.append(f'current workspace {kind} source drifted: {name}')
for authored, bundled in (("cad_mesh.js", "inquiry-cad.js"), ("cad_renderer.js", "inquiry-renderer.js")):
    if (ROOT / "mechanics/cad_v1/viewer" / authored).read_bytes() != (ROOT / "recursivecal_lab/web" / bundled).read_bytes():
        errors.append(f"physical inquiry CAD asset drifted from authored source: {authored}")
archive_files_checked = 0
if args.archive:
    required = [ROOT / name for name in ("LICENSE", "README.md", "CITATION.cff", "CITATION.bib", "MANIFEST.in", "pyproject.toml")]
    for directory in ("docs", "examples", "paper", "research/releases"):
        required.extend(path for path in (ROOT / directory).rglob("*")
                        if path.is_file() and "__pycache__" not in path.parts
                        and path.suffix not in {".pyc", ".aux", ".log", ".out", ".toc", ".bbl", ".blg"})
    with tarfile.open(args.archive, "r:gz") as archive:
        members = {member.name.split("/", 1)[1]: member for member in archive.getmembers()
                   if member.isfile() and "/" in member.name}
        for path in required:
            name = path.relative_to(ROOT).as_posix()
            member = members.get(name)
            if member is None:
                errors.append(f"source archive missing: {name}")
                continue
            if archive.extractfile(member).read() != path.read_bytes():
                errors.append(f"source archive content differs: {name}")
            archive_files_checked += 1
print(json.dumps({"valid": not errors, "errors": errors, "version": __version__,
                  "frozen_models_checked": 2, "archive_files_checked": archive_files_checked}, indent=2))
raise SystemExit(1 if errors else 0)

