# Streaming L-system to SVG

`lsystem_generator` is a Python program that **interprets L-systems** (Lindenmayer systems) and writes the drawing as an **SVG file** (using polylines), intended to be opened in vector editors (Inkscape, Illustrator, Affinity Designer, etc.) for further refinement.

This renderer supports **streaming expansion**: it does **not** need to build the fully-expanded L-system string in memory.

---

## Highlights

- **JSON input** (easy to save, version, tweak, and generate).
- **Streaming expansion** (expands symbols on-the-fly).
- **Extensible turtle command table** (you decide what each symbol does).
- **Branching** with `push`/`pop` (classic L-system `[` and `]`).
- **Editor-friendly SVG** output:
  - multiple `<polyline>` strokes
  - computed `viewBox`
  - optional Y-axis flip so turtle math stays Cartesian
- **Random JSON generator** for experimentation.

---

## Files

- `lsystem_generator.py` — the renderer + random config generator.

---

## Installation

This is a single-file script.

- Requires Python **3.11+**
- No third-party dependencies.

---

## Testing

To run the test suite:

```bash
python -m unittest test_lsystem_generator.py
```

---

## Quick start

### 1) Generate a random config

```bash
python lsystem_generator.py random random.json --seed 123
```

### 2) Render it to SVG

```bash
python lsystem_generator.py render random.json out.svg
```

Open `out.svg` in your vector editor and adjust stroke widths, colors, simplify paths, etc.

---

## Command overview

```bash
python lsystem_generator.py --help
```

### `render`

```bash
python lsystem_generator.py render CONFIG.json OUTPUT.svg
```

Optional flags:

- `--default-action forward_draw|forward_move|noop`
  - What to do with symbols that are **not** present in `turtle.commands`.
  - Default: `forward_draw` (unknown symbols behave like “draw forward”).

### `validate`

```bash
python lsystem_generator.py validate CONFIG.json
```

Parses and validates the JSON structure, then runs a bounded expansion
(up to 10 000 symbols) through the full turtle interpreter.  Reports symbol
count, polyline count, and a warning if the expansion was truncated.  Raises
an error if the config produces no drawable geometry.

### `random`

```bash
python lsystem_generator.py random OUTPUT.json [--seed N]
```

Generates a small, tweakable configuration. The output is intentionally simple and meant for exploration.

---

## JSON input format

The renderer consumes a single JSON file with these main parts:

- L-system definition:
  - `axiom`, `iterations`, `rules`
- Turtle interpretation:
  - `turtle.angle`, `turtle.step`, `turtle.start`, `turtle.commands`
- SVG output:
  - `svg.margin`, `svg.precision`, `svg.flip_y`, `svg.style`, etc.

### Top-level keys

#### `name` (optional)
A string title; written into the SVG `<title>` element.

#### `axiom` (required)
Initial word (string).

#### `iterations` (required)
Integer ≥ 0.

#### `rules` (optional)
An object mapping **single-character** keys to replacement strings.

Example:

```json
"rules": {
  "F": "F+F--F+F",
  "X": "F-[[X]+X]+F[+FX]-X"
}
```

Symbols not present in `rules` rewrite to themselves.

---

## Turtle model

The “turtle” turns symbols into geometry.

### `turtle.angle` (default 90)
The **base** turn angle in degrees.

### `turtle.step` (default 10)
The **base** forward step length.

### `turtle.start` (optional)
Starting state:

```json
"start": {"x": 0, "y": 0, "heading": 90}
```

- `heading` is in degrees.
  - `0` points along +X.
  - `90` points along +Y.

### `turtle.commands`
A mapping of **single-character** symbols to an **action object**.

If a symbol is not present in `turtle.commands`, the program uses a default behavior controlled by `--default-action`.

---

## Action objects

### 1) Forward

```json
"F": {"type": "forward", "draw": true}
```

Fields:

- `type`: must be `"forward"`
- `draw`: boolean
  - `true`: draw a segment
  - `false`: move without drawing (pen up)
- `step` (optional number): multiplier for `turtle.step`

Example (double length move):

```json
"G": {"type": "forward", "draw": true, "step": 2}
```

### 2) Turn (relative)

```json
"+": {"type": "turn", "direction": 1}
"-": {"type": "turn", "direction": -1}
```

Fields:

- `type`: `"turn"`
- `direction`: `+1` or `-1`
- `angle` (optional number): multiplier of `turtle.angle` (default `1`)

Example (half-angle turn):

```json
"a": {"type": "turn", "direction": 1, "angle": 0.5}
```

### 3) Turn (absolute increment)

```json
"|": {"type": "turn_abs", "angle": 180}
```

Adds `angle` degrees to heading.

### 4) Branching

```json
"[": {"type": "push"}
"]": {"type": "pop"}
```

- `push` saves the current turtle state (x, y, heading).
- `pop` restores it.

Implementation detail: after a `pop`, the renderer starts a **new polyline** at the restored point, so branches don’t get connected by accidental strokes.

### 5) No-op

```json
"X": {"type": "noop"}
```

Useful for non-drawing control symbols.

---

## SVG output settings

### `svg.margin` (default 10)
Extra margin added around the computed bounds.  Must be `> 0` if the geometry
is collinear (e.g. a single horizontal or vertical line), otherwise the
viewBox would have zero height or width and rendering will fail.

### `svg.precision` (default 3)
Number of decimal places used in coordinate formatting.

### `svg.flip_y` (default true)
If `true`, wraps geometry in a group transform:

- `translate(0, miny+maxy) scale(1,-1)`

This keeps turtle math in normal Cartesian coordinates (Y up), while SVG’s coordinate system is naturally Y down.

### `svg.width` / `svg.height` (optional)
If set, writes explicit width/height attributes while still using the computed viewBox.

### `svg.background` (optional)
If set to a color string like `"white"` or `"#fff"`, adds a background rectangle.

### `svg.style`

```json
"style": {
  "stroke": "#000",
  "stroke_width": 1,
  "fill": "none",
  "stroke_linecap": "round",
  "stroke_linejoin": "round"
}
```

These are written as attributes on each `<polyline>`.

---

## Example configs

### Koch curve

```json
{
  "name": "Koch curve",
  "axiom": "F",
  "iterations": 4,
  "rules": {"F": "F+F--F+F"},
  "turtle": {
    "angle": 60,
    "step": 10,
    "start": {"x": 0, "y": 0, "heading": 0},
    "commands": {
      "F": {"type": "forward", "draw": true},
      "+": {"type": "turn", "direction": 1},
      "-": {"type": "turn", "direction": -1}
    }
  },
  "svg": {"margin": 10, "precision": 3, "flip_y": true}
}
```

<img src="example/koch.svg" width="300" alt="Example output: Koch curve">

### A simple branching plant-style skeleton

```json
{
  "name": "Tiny plant",
  "axiom": "X",
  "iterations": 5,
  "rules": {
    "X": "F[+X]F[-X]+X",
    "F": "FF"
  },
  "turtle": {
    "angle": 25,
    "step": 6,
    "start": {"x": 0, "y": 0, "heading": 90},
    "commands": {
      "F": {"type": "forward", "draw": true},
      "+": {"type": "turn", "direction": 1},
      "-": {"type": "turn", "direction": -1},
      "[": {"type": "push"},
      "]": {"type": "pop"},
      "X": {"type": "noop"}
    }
  }
}
```

<img src="example/tiny_plant.svg" width="300" alt="Example output: Tiny plant">


### Just another example

```json
{
  "name": "Just another example",
  "axiom": "R+R+R+R",
  "iterations": 5,
  "rules": {
    "R": "R-R+R+R-R"
  },
  "turtle": {
    "angle": 90,
    "step": 0.00411522633744856,
    "start": {
      "x": 0,
      "y": 0,
      "heading": 0
    },
    "commands": {
      "R": {
        "type": "forward",
        "draw": true
      },
      "+": {
        "type": "turn",
        "direction": 1,
        "angle": 1
      },
      "-": {
        "type": "turn",
        "direction": -1,
        "angle": 1
      }
    }
  },
  "svg": {
    "margin": 0.02,
    "precision": 6,
    "flip_y": true,
    "style": {
      "stroke": "#000",
      "stroke_width": 0.002,
      "fill": "none",
      "stroke_linecap": "round",
      "stroke_linejoin": "round"
    }
  }
}
```

<img src="example/just_another_example.svg" width="300" alt="Example output: Just another example">

---

## Design notes and extension ideas

If you want to extend this tool further, the natural next steps are:

- **Multiple styles per symbol** (e.g., different strokes for trunk vs leaves)
- **SVG `<path>` output** with cubic smoothing or simplifying
- **Export layers** (`<g id="...">`) per branch depth or per symbol category
- **Streaming bounds computation** (two-pass: bounds first, then write)
- **Deterministic stochastic rules** (rules as weighted alternatives)

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
