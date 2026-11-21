"""RecursiveCal taskset plugin for Prime Intellect Verifiers v1.

The simulator and JSON protocol work without Verifiers. Install the optional
`verifiers` extra to import and run the full RL taskset plugin.
"""
__all__ = ["RecursiveCalTaskset", "RecursiveCalVerifierEnv"]
try:
    from .taskset import RecursiveCalTaskset, RecursiveCalVerifierEnv
except ModuleNotFoundError as exc:
    if exc.name not in ("verifiers", "verifiers.v1"):
        raise
