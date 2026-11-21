"""Rebuild publication figures and the draft PDF from recorded artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
FIGURES = PAPER / "figures"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--figures-only", action="store_true")
    args = parser.parse_args()
    from recursivecal_lab.experiments import validate_artifacts
    verified = validate_artifacts(ROOT / "research/releases/v0.3")
    if not verified["valid"]:
        raise RuntimeError("Experiment evidence failed verification: " + str(verified["errors"]))
    summary = json.loads((ROOT / "research/releases/v0.3/summary.json").read_text())
    audit = json.loads((ROOT / "research/releases/physical-v1/audit.json").read_text())
    run = json.loads((ROOT / "research/releases/physical-v1/open_run.json").read_text())
    fit = json.loads((ROOT / "research/releases/physical-v1/synthetic_force_fit.json").read_text())
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.labelcolor": "#203247", "text.color": "#203247",
                         "axes.titleweight": "bold", "svg.hashsalt": "recursivecal-v0.3"})
    def save(fig, name):
        fig.savefig(FIGURES / (name + ".png"), dpi=220, bbox_inches="tight")
        fig.savefig(FIGURES / (name + ".svg"), bbox_inches="tight", metadata={"Date": None})
        plt.close(fig)

    cohorts = list(summary["results"])
    labels = ["Finite prior", "Parameter\njitter", "Unseen\nhigh load", "Extreme\ndeadzone", "Directional\nfriction"]
    policies = [("no_probe_prior_calibration", "No diagnostic test", "#838d97"),
                ("best_fixed", "Best fixed schedule", "#263c54"),
                ("bayesian_adaptive", "Adaptive Bayes", "#0a8f7a"),
                ("learned", "Learned: five-seed mean", "#e29b38"),
                ("bayesian_abstain", "Bayes + abstention", "#735caa")]
    fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
    for i, (policy, label, color) in enumerate(policies):
        values = [summary["results"][c]["learned_training_seed_summary"]["mean"] if policy == "learned"
                  else summary["results"][c]["policies"][policy]["mean_reward"] for c in cohorts]
        ax.scatter(np.arange(len(cohorts)) + (i - 2) * .12, values, color=color, s=45, label=label, zorder=3)
    ax.set_xticks(np.arange(len(cohorts)), labels)
    ax.set_ylim(.48, .97)
    ax.set_ylabel("Mean net reward (higher is better)")
    ax.grid(axis="y", color="#dbe1e5", linewidth=.6)
    ax.legend(loc="upper center", bbox_to_anchor=(.5, -.18), ncols=3, frameon=False, fontsize=9)
    save(fig, "policy_results")

    fig, ax = plt.subplots(figsize=(8, 3.4), layout="constrained")
    for i, c in enumerate(cohorts):
        comparison = summary["results"][c]["paired_comparisons"]["bayesian_adaptive minus best_fixed"]
        mean = comparison["mean_difference"]
        lo, hi = comparison["ci95"]
        ax.errorbar(mean, i, xerr=[[max(0, mean - lo)], [max(0, hi - mean)]], fmt="o",
                    color="#0a8f7a" if mean > 0 else "#b64242", capsize=4, markersize=6)
    ax.axvline(0, color="#536475", linewidth=1)
    ax.set_yticks(range(len(cohorts)), [label.replace("\n", " ") for label in labels])
    ax.invert_yaxis()
    ax.set_xlabel("Adaptive Bayes minus fixed reward; paired 95% interval")
    ax.grid(axis="x", color="#dbe1e5", linewidth=.6)
    save(fig, "paired_comparisons")

    trace = run["trace"]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.3), layout="constrained")
    axes[0].plot([r["time_s"] for r in trace], np.degrees([r["target_angle_rad"] for r in trace]),
                 color="#93a2ae", linestyle="--", label="Target")
    axes[0].plot([r["time_s"] for r in trace], np.degrees([r["angle_rad"] for r in trace]), color="#0a8f7a", label="Synthetic angle")
    axes[0].set(xlabel="Time (s)", ylabel="Hinge angle (degrees)", title="SI model: nominal opening")
    axes[0].legend(frameon=False, fontsize=9)
    refinement = audit["numerical_verification"]["trajectory_refinement"][:-1]
    axes[1].loglog([r["dt_s"] for r in refinement], [r["final_angle_difference_from_finest_rad"] for r in refinement], "o-", color="#263c54")
    axes[1].set(xlabel="Integration step (s)", ylabel="Final-angle difference (rad)", title="Refinement at 2.553 s")
    axes[1].grid(which="both", color="#dbe1e5", linewidth=.6)
    save(fig, "physical_model")

    fig, ax = plt.subplots(figsize=(7.5, 3.4), layout="constrained")
    predictions = fit["predictions"]
    for split, color, marker in [("train", "#263c54", "o"), ("validation", "#e29b38", "s")]:
        rows = [r for r in predictions if r["split"] == split]
        ax.scatter([r["length_m"] for r in rows], [r["observed_force_N_each"] for r in rows],
                   label=f"Synthetic {split}", color=color, marker=marker, s=32)
    rows = sorted(predictions, key=lambda r: r["length_m"])
    ax.plot([r["length_m"] for r in rows], [r["predicted_force_N_each"] for r in rows], color="#0a8f7a", label="Training-only fit")
    ax.set(xlabel="Pin-to-pin length (m)", ylabel="Force per strut (N)")
    ax.grid(color="#dbe1e5", linewidth=.6)
    ax.legend(frameon=False, fontsize=9)
    save(fig, "force_fit")
    print("Built four figures from verified release data.")
    if args.figures_only:
        return
    for executable in ("pandoc",):
        if shutil.which(executable) is None:
            raise SystemExit(f"Figures complete. PDF requires {executable}; install the documented Pandoc/LaTeX toolchain or use manuscript.md.")
    common = ["pandoc", "paper/manuscript.md", "--from=markdown", "--standalone", "--citeproc",
              "--bibliography=paper/references.bib", "--resource-path=.:paper", "--number-sections",
              "-V", "geometry:margin=0.9in", "-V", "fontsize=10pt", "-V", "colorlinks=true",
              "-V", "urlcolor=blue", "-V", "linkcolor=black", "-V", "documentclass=article"]
    subprocess.run(common + ["--output=paper/manuscript.tex"], cwd=ROOT, check=True)
    from render_paper import render
    render(ROOT)
    print("Built paper/manuscript.tex and paper/RecursiveCal_Manuscript.pdf.")


if __name__ == "__main__":
    main()

