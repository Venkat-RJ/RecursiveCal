# RecursiveCal Virtual Test Cell

Open **[index.html](index.html)** offline to explore the synthetic RecursiveCal actuator environment. Choose one of seven fault scenarios, run diagnostic probes, tune a controller, or click **Run Bayesian diagnosis**. The factory and calibrated runs can be replayed side by side.

The two views are **SUV liftgate**, a recognizable vehicle illustration driven by normalized actuator position, and **Actuator test bench**, the one-axis simulator representation. The liftgate's geometry, hinge, and strut are **illustrative**, not a validated multibody model. No hardware is connected.

**Signal colors:** blue `#4F9FE8` target; teal `#35C8A6` actual/calibrated motion; amber `#E8A348` fault/factory response; purple `#A98AEF` diagnostic test; red `#E35D64` intervention or negative result. Labels and dash patterns supplement colors.

The physical measurements and scores use the simulator equations. The before/after replay shows one common trajectory; quality is measured on four trajectories. The demo's automated policy is a **classical Bayesian reference**, not an RL-trained model. Hidden parameters are embedded in this local browser teaching demo and must never be served to an RL training agent.

```bash
python visualization/build.py
node --check visualization/app.js
```

Run from the repository root. The final HTML contains all CSS, JS, and scenario data. No external scripts or libraries are required. See [research results](../RESULTS.md) and the [RL pilot](../RL_PILOT.md).
