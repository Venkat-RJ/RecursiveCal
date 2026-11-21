# Why RecursiveCal exists

The original Prime Intellect RL Residency proposal asked:

> Can RL teach agents how to experiment with unfamiliar physical systems?

The practical origin was Bayesian optimization for power-liftgate calibration. The open research problem is what the agent should do when the system is unfamiliar or its behavior changes: which safe test to run, how to interpret the observation, what assumption to challenge, when to stop, and what calibration to deploy.

The earliest RL pilot learned a nonadaptive fixed probe. A better Bayesian method recovered much of the simple task. Those are important negative results; the goal is not to hide them behind a new benchmark that guarantees an RL win.

The present sequential task is a **necessary intermediate gate**, not the full problem. It uses independent fixture resets, a known ten-model bank, an existing Bayesian terminal calibrator, and bounded discrete test actions. It does not yet perform model creation, online adaptation of the physical laws, safe deployment, or true out-of-prior generalization.

Research priority: baseline-first, mechanism-first, and auditable comparisons. Preserve the historical v0.3 results. Do not label this a new RL result until an actual trained policy has been fairly tested.