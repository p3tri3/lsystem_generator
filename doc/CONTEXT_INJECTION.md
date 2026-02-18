# PROJECT CONTEXT INJECTION (AI-AGENT OPTIMIZED)

This document is meant to be pasted into a new chat/agent session to quickly transfer accurate context and reduce hallucinations. It favors concrete, verifiable details and explicitly separates **facts** (current implementation) from **intent** (design goals) and **extension space** (things that may change).

---

# PROJECT TYPE
Command-line application — Python 3.11+ — single-script implementation.

Primary artifacts:
- `lsystem_generator.py` (CLI + engine + SVG writer)
- `test_lsystem_generator.py` (Unit tests)
- JSON config files (inputs)
- SVG files (outputs)
- `README.md` (user-facing documentation)

---

# PROJECT VISION (INTENT)
Build a general-purpose, extensible L-system (Lindenmayer system) generator that renders to **clean, editor-friendly SVG** for further refinement in vector drawing programs.

Key user workflow:
1) Write or generate a JSON config describing grammar + turtle interpretation + SVG preferences  
2) Run the CLI to produce an SVG  
3) Open SVG in a vector editor and refine (stroke width, layout, colors, composition, etc.)

The output should be deterministic and reproducible when given the same config and seed.

---

# WHAT EXISTS TODAY (FACTS)
The current implementation is delivered as a single Python script, `lsystem_generator.py`, with subcommands:

- `render <config.json> <output.svg>`
- `validate <config.json>`
- `random <output.json> [--seed N]` (generates an experimental random config)

There appears to be a test suite `test_lsystem_generator.py` using `unittest`.

The engine supports:
- Deterministic rewriting rules (`rules`: symbol -> replacement string)
- Streaming expansion (does not require building the full expanded string in memory)
- Turtle interpretation with:
  - forward drawing/moving
  - turns with configurable angles
  - branching via push/pop stack
  - multiple polylines (to avoid accidental connections between disjoint strokes)

SVG output:
- Uses one or more `<polyline>` elements
- Computes bounding box and writes an appropriate `viewBox`
- Optional coordinate flip for Y axis (keep internal math Cartesian)

See example subfolder for example files created during development

---

# CONCEPTUAL MODEL (DON’T HALLUCINATE)
There are three conceptually separate phases:

1) **Grammar expansion** (symbolic)
   - Inputs: `axiom`, `rules`, `iterations`
   - Output: a stream of symbols (characters) representing the expanded L-system

2) **Turtle interpretation** (geometric)
   - Inputs: symbol stream + command mapping + start state + step/angle
   - Output: a list of polylines (each polyline is a list of points)

3) **SVG rendering** (formatting)
   - Inputs: polylines + style + viewBox logic
   - Output: SVG file

Agents should preserve this separation when modifying/adding features.

---

# ARCHITECTURE (CURRENT + PREFERRED DIRECTION)
Current: single-file script with internal functions.

Preferred (not required; do not over-constrain):
- CLI layer (args, file I/O, help, errors)
- Engine layer (expansion + turtle)
- Renderer layer (SVG, bounds, transforms)

A future refactor may split into modules, but keep interfaces stable.

---

# INPUT CONFIG (JSON) — FACTUAL CONTRACT
Top-level keys (typical):
- `name` (string, optional)
- `axiom` (string, required)
- `iterations` (int >= 0, required)
- `rules` (object mapping single-character symbols to replacement strings, required)
- `turtle` (object, required)
- `svg` (object, optional but usually provided)

`turtle` section typically includes:
- `angle` (float, degrees)
- `step` (float)
- `start`: `{ "x": float, "y": float, "heading": float_degrees }`
- `commands`: object mapping symbols to actions

Action types currently used:
- `forward` with `draw: true/false`
- `turn` with `direction` (+1 left, -1 right) and optional multiplier fields
- `push`
- `pop`
- `noop`

`svg` section typically includes:
- `margin` (float)
- `precision` (int)
- `flip_y` (bool)
- `style` (object: `stroke`, `stroke_width`, `fill`, `stroke_linecap`, `stroke_linejoin`, etc.)

Important: The exact schema may expand; avoid breaking existing configs.

---

# INVARIANTS (KEEP THESE)
These are high-signal invariants; keep them unless there is a deliberate redesign:

- Given the same JSON config and seed, output geometry is deterministic.
- Expansion logic is independent of SVG formatting.
- Turtle interpretation is independent of SVG formatting.
- SVG is produced as vector primitives (polylines) suitable for editing.
- `render` should not silently “fix” configs; config validation should be explicit.

---

# NON-GOALS (RIGHT NOW)
Avoid inventing new requirements unless requested:

- No requirement for GUI preview.
- No requirement for external dependencies (keep stdlib-only unless there is a strong reason).

---

# FAILURE MODES / PITFALLS (BEWARE)
If you change the system, consider these:

- Random grammars can explode exponentially; add optional safety limits if needed:
  - max expanded symbols
  - max drawn segments
  - max stack depth
- SVG coordinate space: SVG y-axis is downward; if you change transforms, ensure output orientation remains consistent.
- Branching: after `pop`, continuing the same polyline can create unwanted connecting segments; the current approach uses separate polylines for disjoint strokes.

---

# EXTENSION SPACE (OK TO ADD)
These are expected/likely extensions; do not treat them as required:

- Stochastic/weighted rules (with seed-controlled randomness)
- Parametric L-systems (symbols with parameters)
- Context-sensitive rules
- Per-symbol styling (stroke width/color by symbol, layers/groups)
- Output `<path>` option in addition to `<polyline>`
- Two-pass streaming (pass 1 bounds, pass 2 write SVG) for extreme sizes
- Export of metadata (e.g., JSON summary of bounds, segment count)

When adding features, prefer:
- Backward-compatible JSON keys
- Clear help text and README updates
- Deterministic behavior with explicit seeds

---

# REPRODUCTION CHECKLIST (FOR NEW AGENT)
To confirm you are aligned with the project goal:

1) Run:
   - `python -m unittest test_lsystem_generator.py`
   - `python lsystem_generator.py validate example/koch.json`
   - `python lsystem_generator.py render example/koch.json out.svg`
2) Open `out.svg` in a vector editor and confirm:
   - It’s scalable and editable
   - It uses polylines
   - Geometry looks like the expected fractal/shape

If changing math/transforms:
- Re-render the Koch example to ensure no regressions in basic functionality.

---

# EDITING PRINCIPLES (FOR AGENTS)
- Prefer small, testable changes over large rewrites.
- Keep user-facing config format clear and documented.
- If behavior changes, document it and provide migration notes (do not silently break existing configs).
- Don’t assume missing features exist — check the code first.
