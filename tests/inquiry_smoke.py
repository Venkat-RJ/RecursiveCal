"""Compatibility entry point for the unified physical workspace acceptance test."""
import argparse
from pathlib import Path

from workspace_smoke import ROOT, run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/inquiry-browser")
    parser.add_argument("--browser-path")
    args = parser.parse_args()
    run(args.output, args.browser_path)
