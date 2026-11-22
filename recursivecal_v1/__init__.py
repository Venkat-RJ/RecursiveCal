"""RecursiveCal taskset plugin for Prime Intellect Verifiers v1.

The simulator and JSON protocol work without Verifiers. Install the optional
`verifiers` extra to import and run the full RL taskset plugin.
"""
from importlib import import_module

# Preserve the historical plugin's identity. The SDK rejects multiple Taskset
# exports in one module; the physical plugin is registered as recursivecal-physical.
__all__ = ["RecursiveCalTaskset", "RecursiveCalVerifierEnv"]
_EXPORTS = {
    "RecursiveCalTaskset": ".taskset", "RecursiveCalVerifierEnv": ".taskset",
    "PhysicalCalibrationTaskset": ".physical_taskset",
    "PhysicalCalibrationVerifierEnv": ".physical_taskset",
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))
