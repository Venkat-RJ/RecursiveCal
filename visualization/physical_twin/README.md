# RecursiveCal: Physical tailgate test cell

A 3D model-in-the-loop demonstration, separate from the normalized actuator RL task in this repository.

The view is a **parameterized, illustrative mechanism**. A rotating hatch is connected by two telescoping struts. The hinge angle and strut extension are derived from the same simulation, with modeled gravity torque, hinge friction, a force-limited actuator controller, and seven fault conditions.

Open [the standalone demo](demo.html) for an installation-free version. For the editable source version, serve this directory with `python -m http.server` and open `index.html`.

**Controls:** orbit and zoom the model, play or scrub the opening cycle, inject faults, change controller gains, compare factory and modified responses, switch to a translucent mechanism view, and open immersive 3D view.

The **reference calibration** button uses the known hidden plant parameters. It is an oracle comparison, not an RL policy. The physical parameters and body geometry are illustrative, not measured from an OEM system. No real-hardware safety claim or vehicle-certified model is made.

The 3D scene uses a custom WebGL2 renderer and a software 3D fallback for environments where WebGL is unavailable. No external libraries or image assets are required. Physics is integrated at 10 ms steps.

See the existing [RecursiveCal research README](../../README.md) for the separate RL experimental environment.
