# RecursiveCal interactive visual laboratory

**Open [index.html](index.html) in your browser.** This is a standalone offline visualization, not an AI model or a physical actuator controller.

Choose a synthetic system, run a bounded diagnostic pulse, see its noisy measurements and moving actuator, adjust controller gain/friction compensation/encoder offset, and test the result. **Replay Bayesian diagnosis** replays two precomputed diagnostic actions and a calibration produced by the existing classical Bayesian Python baseline. It is not an RL-trained policy.

The browser uses the same normalized actuator dynamics, 20-ms simulation step, action bounds and calibration-quality formula as the canonical Python `recursivecal.py`. The local development parity test compared 28 simulator/parameter combinations and found agreement within 1.2e-16 in numerical outputs.

**Safety and research boundary:** The HTML intentionally embeds ground-truth plant parameters for animation. All seven scenarios are dedicated showcase seeds (70,000,000+), separate from training and held-out evaluation ranges. Do not train on or score agents in the browser. The real Verifiers environment keeps ground truth and rewards host-side. Browser demo measurement noise follows the same Gaussian noise model but uses a deterministic browser generator rather than the exact Python sequential RNG. This is synthetic physics and provides no evidence for hardware safety.

Sources:
- `engine.js`: numerical physics port used for rendering and scoring
- `app.js`: user interaction and animation
- `styles.css`: responsive visual design
- `scenarios.json`: frozen Python simulator/Bayesian replay showcase data
- `template.html`: source HTML shell
- `index.html`: self-contained distributable, no dependencies

To regenerate the standalone demo after changing source files, run `python visualization/build.py` from the repo root (see script).
