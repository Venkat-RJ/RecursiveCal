"""Foreground engineering fixture audit, with full reproducible reports.

This is not a statistical research benchmark. Named fixtures include development
cases, and a single seed is a software acceptance check rather than an estimate
of generalization. Keep that distinction in exported evidence.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recursivecal_lab.inquiry import CASE_LABELS, run_study, verify_report, digest
from recursivecal_lab.io import write_json


def run(output: Path, cases: list[str], policies: list[str], seed: int) -> None:
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    rows, files = [], []
    for case in cases:
        for policy in policies:
            print(f"Running {case} / {policy} / seed {seed}", flush=True)
            report = run_study(case=case, policy=policy, seed=seed)
            check = verify_report(report)
            if not check['valid']:
                raise ValueError(check)
            name = f"{case}-{policy}-seed{seed}.json.gz"
            raw = json.dumps(report, separators=(',', ':'), allow_nan=False).encode()
            blob = gzip.compress(raw, mtime=0)
            (output / name).write_bytes(blob)
            files.append({'path': name, 'sha256': hashlib.sha256(blob).hexdigest(),
                          'report_sha256': report['report_sha256']})
            row = {'case': case, 'policy': policy, 'seed': seed, 'outcome': report['outcome'],
                   'tests': len(report['agent_history']), 'cost': report['cost'],
                   'actions': [x['action'] for x in report['agent_history']],
                   'model_mismatch': report['final_belief']['model_mismatch'],
                   'directions_observed': report['final_belief']['directions_observed'],
                   'before_mean_rmse_deg': report['verification']['before_mean_rmse_deg'],
                   'after_mean_rmse_deg': report['verification']['after_mean_rmse_deg'],
                   'passed_profiles': sum(x['after']['accepted'] for x in report['verification']['comparisons']),
                   'reason': report['commitment']['reason']}
            rows.append(row)
            print(f"  {row['outcome']}; tests {row['tests']}; cost {row['cost']:.1f}; RMSE {row['before_mean_rmse_deg']:.3f} -> {row['after_mean_rmse_deg']:.3f}; profiles {row['passed_profiles']}/4", flush=True)
    summary = {'schema_version': 'recursivecal.physical-fixture-audit/1', 'seed': seed,
               'scope': 'Synthetic development fixture suite. No population inference, preregistration or RL advantage claim.',
               'unique_physical_conditions': len(cases), 'policy_runs': len(rows), 'results': rows,
               'source_sha256': report['provenance']['source_sha256'],
               'wall_seconds': round(time.perf_counter() - started, 3), 'hardware_validated': False}
    summary['summary_sha256'] = digest(summary)
    write_json(output / 'summary.json', summary)
    write_json(output / 'manifest.json', {'files': files, 'source_sha256': summary['source_sha256']})
    print(f"Saved {len(rows)} complete, integrity-checked reports to {output}", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=list(CASE_LABELS), default=list(CASE_LABELS))
    parser.add_argument('--policies', nargs='+', choices=['bayes', 'fixed', 'no_probe'], default=['bayes','fixed','no_probe'])
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()
    run(args.output, args.cases, args.policies, args.seed)
