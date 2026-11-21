"""Verify local documentation, frozen source, and bundled evidence consistency."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
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
if audit["provenance"]["model_source_sha256"] != hashlib.sha256((ROOT / "recursivecal_lab/physics.py").read_bytes()).hexdigest():
    errors.append("physical audit source differs from implementation")
if (ROOT / "docs/EXPERIMENT_PROTOCOL.md").read_bytes() != (ROOT / "recursivecal_lab/data/EXPERIMENT_PROTOCOL.md").read_bytes():
    errors.append("installed experiment protocol differs from documentation")
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

