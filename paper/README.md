# Manuscript and reproducibility package

The [working manuscript](manuscript.md) presents RecursiveCal as a reproducible synthetic diagnostic study and a local software-in-the-loop instrument. It reports adaptive gains under a constructed prior, failures under structural mismatch, and numerical checks for a separate physical-unit model. It does not claim general RL superiority, a validated vehicle twin, or a completed hardware deployment.

The [PDF manuscript](RecursiveCal_Manuscript.pdf) and figures are generated from saved release evidence. This is a draft for author review, not a submitted or peer-reviewed paper. No venue, acceptance, DOI, affiliation, or external validation is invented.

## Build

From the repository root:

```bash
python -m pip install -e '.[paper]'
python scripts/build_paper.py
```

Figure generation uses Matplotlib. Pandoc resolves the bibliography and exports editable LaTeX. ReportLab renders the PDF from the same Pandoc document, including mathematical equations and data figures, so a LaTeX installation is not required. Install the Pandoc executable separately if it is absent. The editable Markdown and data remain usable without the PDF toolchain.

## Evidence

- [Experiment protocol](../docs/EXPERIMENT_PROTOCOL.md)
- [Raw diagnostic experiment and checkpoints](../research/releases/v0.3/)
- [Physical audit and representative trace](../research/releases/physical-v1/)
- [Source and data provenance](../docs/PROVENANCE.md)
- [Physical measurement protocol](../docs/HARDWARE_PROTOCOL.md)

Any later submission should identify its exact source revision and artifact hashes. If a paper adds hardware claims, it must add independent measured data and the corresponding held-out comparison. The current evidence already supports a transparent software and synthetic-benchmark report; its suitability and novelty for a particular venue require the author's judgment.

