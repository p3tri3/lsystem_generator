# AGENTS.md

Repository guidance for **AI coding agents**.

## Project

General-purpose **L-system (Lindenmayer system) generator** that renders **clean, editor-friendly SVG** for refinement in vector editors.

- Type: CLI tool
- Language: **Python 3.11+**
- Current implementation: single script (see module map below)
- Primary outputs: SVG composed of vector primitives (polylines)

## Quick commands

```bash
pytest
python lsystem_generator.py validate <config.json>
python lsystem_generator.py render <config.json> <output.svg>
python lsystem_generator.py random <output.json> --seed 123
ruff check .
ruff check . --fix
mypy .
```

## Conceptual model (do not collapse layers)

Keep these phases conceptually separate when changing or extending the project:

1) **Grammar expansion** (symbolic)
   - Inputs: `axiom`, `rules`, `iterations`
   - Output: a stream of symbols (characters)

2) **Turtle interpretation** (geometric)
   - Inputs: symbol stream + command mapping + start state + step/angle
   - Output: a list of **polylines** (each is a list of points)

3) **SVG rendering** (formatting)
   - Inputs: polylines + style + viewBox/bounds logic
   - Output: SVG file

## Architecture (current and preferred direction)

- Current: single-file script with internal functions.
- Preferred direction (optional, do not over-constrain): separate **CLI / Engine / Renderer** layers.
  A future refactor may split modules; keep interfaces stable.

## JSON config contract (backward-compatible)

Top-level keys (typical):
- `name` (string, optional)
- `axiom` (string, required)
- `iterations` (int >= 0, required)
- `rules` (object: single-character symbol → replacement string, required)
- `turtle` (object, required)
- `svg` (object, optional but usually provided)

`turtle` (typical):
- `angle` (float, degrees)
- `step` (float)
- `start`: `{ "x": float, "y": float, "heading": float_degrees }`
- `commands`: object mapping symbols to actions

Action types used:
- `forward` with `draw: true/false`
- `turn` with `direction` (+1 left, -1 right) and optional multipliers
- `push`
- `pop`
- `noop`

`svg` (typical):
- `margin` (float)
- `precision` (int)
- `flip_y` (bool)
- `style` (object: `stroke`, `stroke_width`, `fill`, `stroke_linecap`, `stroke_linejoin`, etc.)

**Compatibility rule:** schema may expand; avoid breaking existing configs. Prefer additive keys and explicit migration notes.

## Invariants (do not violate unless redesigning)

- Given the same JSON config and seed, **output geometry is deterministic**.
- Expansion is independent of SVG formatting.
- Turtle interpretation is independent of SVG formatting.
- SVG output uses **vector primitives** suitable for editing (polylines by default).
- `render` should not silently “fix” configs; validation should be explicit (`validate`).
- `validate` runs a bounded expansion (≤ 10 000 symbols via `itertools.islice`) through the full turtle interpreter and raises `ConfigError` if the config produces no drawable geometry.

## Non-goals

- No GUI preview requirement.
- No external dependencies (prefer stdlib-only unless there is a strong reason).

## Failure modes / pitfalls

- **Exponential growth:** random grammars can explode. `validate` samples at most 10 000 symbols to give a fast preview.
  If adding new generators/features, consider additional safety limits:
  - max drawn segments
  - max stack depth
- **SVG coordinate system:** SVG Y axis is downward; if transforms change, keep output orientation consistent.
- **Branching:** after `pop`, continuing the same polyline can create unwanted connecting segments.
  Use separate polylines for disjoint strokes.

## Extension space (optional ideas, not requirements)

- Stochastic/weighted rules (seed-controlled)
- Parametric or context-sensitive L-systems
- Per-symbol styling (layers/groups)
- Optional `<path>` output in addition to `<polyline>`
- Two-pass streaming for extreme sizes (bounds pass then render pass)
- Metadata export (bounds, segment count)

## Editing principles

- Prefer small, testable changes over large rewrites.
- Keep config format clear; update `README.md` and `--help` when behavior changes.
- If behavior changes, document it and provide migration notes; do not silently break configs.
- Don’t assume features exist—check the code first.

## Module map

- `lsystem_generator.py` — CLI + engine + SVG writer (current single-file entry)
- `test_lsystem_generator.py` — unit tests
- `README.md` — user-facing docs
- `example/` — sample configs (if present)
