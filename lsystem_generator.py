#!/usr/bin/env python3
"""lsystem_generator.py

A general, streaming L-system interpreter that renders to SVG.

Key features:
- JSON-based input configuration.
- Streaming expansion (no need to materialize the fully expanded string).
- Extensible turtle command table.
- Branching via push/pop.
- Multi-polyline output (vector-editor friendly).
- Random config generator for experimentation.

Run:
  python lsystem_generator.py render config.json output.svg
  python lsystem_generator.py random out.json --seed 123
  python lsystem_generator.py --help
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import random
import sys
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from typing import Any, Literal, cast

Point = tuple[float, float]


# -------------------------
# Errors / Validation
# -------------------------


class ConfigError(ValueError):
    pass


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def _as_float(x: Any, path: str) -> float:
    _require(isinstance(x, (int, float)), f"{path} must be a number")
    return float(x)


def _as_int(x: Any, path: str) -> int:
    _require(
        isinstance(x, int) and not isinstance(x, bool), f"{path} must be an integer"
    )
    return int(x)


def _as_str(x: Any, path: str) -> str:
    _require(isinstance(x, str), f"{path} must be a string")
    return cast(str, x)


def _as_bool(x: Any, path: str) -> bool:
    _require(isinstance(x, bool), f"{path} must be a boolean")
    return cast(bool, x)


def _as_dict(x: Any, path: str) -> dict[str, Any]:
    _require(isinstance(x, dict), f"{path} must be an object")
    return cast(dict[str, Any], x)


# -------------------------
# Command model
# -------------------------


@dataclass(frozen=True)
class TurtleState:
    x: float
    y: float
    heading_deg: float


@dataclass(frozen=True)
class SvgStyle:
    stroke: str = "#000"
    stroke_width: float = 1.0
    fill: str = "none"
    stroke_linecap: str = "round"
    stroke_linejoin: str = "round"


@dataclass(frozen=True)
class RenderConfig:
    name: str
    axiom: str
    iterations: int
    rules: dict[str, str]

    angle_deg: float
    step: float
    start: TurtleState

    # command table: symbol -> action dict
    commands: dict[str, dict[str, Any]]

    # svg
    margin: float
    precision: int
    flip_y: bool
    width: float | None
    height: float | None
    style: SvgStyle
    background: str | None


# -------------------------
# Streaming expansion
# -------------------------


def stream_expand(
    axiom: str, rules: dict[str, str], iterations: int
) -> Generator[str, None, None]:
    """Yield expanded symbols in order without building the full string.

    Uses an explicit stack of (string, index, depth) frames.
    """
    _require(iterations >= 0, "iterations must be >= 0")

    # Frame: (current_string, index, depth)
    stack: list[tuple[str, int, int]] = [(axiom, 0, 0)]

    while stack:
        s, i, d = stack.pop()
        if i >= len(s):
            continue

        ch = s[i]
        # Push continuation of current frame
        stack.append((s, i + 1, d))

        if d < iterations and ch in rules:
            repl = rules[ch]
            # Push replacement AFTER continuation so it sits on top of the
            # stack and is popped first.  This preserves left-to-right symbol
            # order: continuation waits while replacement is fully traversed.
            stack.append((repl, 0, d + 1))
        else:
            yield ch


# -------------------------
# Turtle interpreter
# -------------------------


@dataclass
class PolylineBuffer:
    polylines: list[list[Point]]

    def start_new(self, p: Point) -> None:
        self.polylines.append([p])

    def current(self) -> list[Point]:
        if not self.polylines:
            raise RuntimeError("current() called before start_new()")
        return self.polylines[-1]

    def add_point(self, p: Point) -> None:
        cur = self.current()
        if not cur:
            cur.append(p)
        else:
            if cur[-1] != p:
                cur.append(p)


_DefaultAction = Literal["forward_draw", "forward_move", "noop"]


def interpret_to_polylines(
    symbols: Iterable[str],
    *,
    commands: dict[str, dict[str, Any]],
    angle_deg: float,
    step: float,
    start: TurtleState,
    default_action: _DefaultAction = "forward_draw",
) -> list[list[Point]]:
    """Interpret streamed symbols to polylines.

    The command dict supports action types:
      - {"type":"forward", "draw": true|false, "step": <optional multiplier>}
      - {"type":"turn", "direction": +1|-1, "angle": <optional multiplier or abs deg>}
      - {"type":"turn_abs", "angle": <degrees>}
      - {"type":"push"}
      - {"type":"pop"}
      - {"type":"noop"}

    Any symbol not in commands uses default_action:
      - "forward_draw": draw forward
      - "forward_move": move forward without drawing
      - "noop": ignore
    """

    _require(step > 0, "turtle.step must be > 0")
    _require(
        default_action in ("forward_draw", "forward_move", "noop"),
        (
            "default_action must be 'forward_draw', 'forward_move', or 'noop'; got "
            f"{default_action!r}"
        ),
    )

    x, y, h = start.x, start.y, start.heading_deg

    buf = PolylineBuffer(polylines=[])
    buf.start_new((x, y))

    # stack stores turtle state plus a flag whether we should continue current polyline
    stack: list[TurtleState] = []

    for sym in symbols:
        action = commands.get(sym)
        if action is None:
            if default_action == "forward_draw":
                action = {"type": "forward", "draw": True}
            elif default_action == "forward_move":
                action = {"type": "forward", "draw": False}
            else:
                action = {"type": "noop"}

        atype = action.get("type")
        _require(
            isinstance(atype, str), f"command for '{sym}' must have string field 'type'"
        )

        if atype == "noop":
            continue

        if atype == "turn":
            direction = action.get("direction")
            _require(
                direction in (-1, 1),
                f"turn command for '{sym}' must have direction -1 or 1",
            )
            if not isinstance(direction, int):
                raise TypeError(
                    f"Expected int direction, got {type(direction).__name__}"
                )
            a = action.get("angle", 1)
            if isinstance(a, (int, float)):
                # If a looks like a multiplier (default 1) we multiply by base angle.
                # If user wants an absolute number of degrees, they can use turn_abs.
                h += direction * float(a) * angle_deg
            else:
                raise ConfigError(
                    f"turn command for '{sym}' field 'angle' must be a number"
                )
            continue

        if atype == "turn_abs":
            a = action.get("angle")
            h += _as_float(a, f"command '{sym}'.angle")
            continue

        if atype == "push":
            # Do NOT start a new polyline here.  The branch geometry begins
            # from the current pen position and is appended to the active
            # polyline.  A new polyline is started only on `pop` (after
            # restoring state) to prevent an unwanted connecting stroke from
            # the branch tip back to the trunk continuation point.
            stack.append(TurtleState(x, y, h))
            continue

        if atype == "pop":
            _require(bool(stack), f"pop command '{sym}' encountered with empty stack")
            st = stack.pop()
            x, y, h = st.x, st.y, st.heading_deg
            # Start a new polyline at the restored point to prevent unwanted
            # connecting strokes.
            buf.start_new((x, y))
            continue

        if atype == "forward":
            draw = action.get("draw")
            _require(
                isinstance(draw, bool),
                f"forward command for '{sym}' must have boolean field 'draw'",
            )
            mult = action.get("step", 1)
            _require(
                isinstance(mult, (int, float)),
                f"forward command for '{sym}' field 'step' must be a number",
            )
            dist = step * float(mult)
            rad = math.radians(h)
            nx = x + dist * math.cos(rad)
            ny = y + dist * math.sin(rad)

            if draw:
                buf.add_point((nx, ny))
            else:
                # Move without drawing: start a new polyline at destination
                buf.start_new((nx, ny))

            x, y = nx, ny
            continue

        raise ConfigError(f"Unknown command type '{atype}' for symbol '{sym}'")

    # Cleanup: remove empty or 1-point polylines
    out: list[list[Point]] = []
    for pl in buf.polylines:
        if len(pl) >= 2:
            out.append(pl)
    return out


# -------------------------
# SVG writing
# -------------------------


def _ensure_parent_dir(path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)


def compute_bounds(polylines: list[list[Point]]) -> tuple[float, float, float, float]:
    _require(len(polylines) > 0, "No drawable geometry produced.")
    min_x = min_y = math.inf
    max_x = max_y = -math.inf
    for pl in polylines:
        for x, y in pl:
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
    return (min_x, min_y, max_x, max_y)


def _fmt(x: float, precision: int) -> str:
    # Normalise -0.0 so it never produces "-0" in SVG output.
    if not x:
        x = 0.0
    # Strip trailing zeros for nicer SVG.
    s = f"{x:.{precision}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def write_svg(
    polylines: list[list[Point]],
    *,
    out_path: str,
    margin: float,
    precision: int,
    flip_y: bool,
    width: float | None,
    height: float | None,
    style: SvgStyle,
    background: str | None,
    title: str | None = None,
) -> None:
    minx, miny, maxx, maxy = compute_bounds(polylines)

    # Add margin in user units before checking dimensions so that valid
    # collinear geometry (e.g. a single horizontal line where h==0) can be
    # rescued by a nonzero margin.
    minx -= margin
    miny -= margin
    maxx += margin
    maxy += margin
    w = maxx - minx
    h = maxy - miny
    _require(
        w > 0 and h > 0,
        "Degenerate bounds after margin (width or height is zero). "
        "Set svg.margin > 0 to render collinear or single-point geometry.",
    )

    # If width/height are specified, we keep viewBox but set explicit size.
    svg_w_attr = f' width="{_fmt(float(width), precision)}"' if width else ""
    svg_h_attr = f' height="{_fmt(float(height), precision)}"' if height else ""

    view_box = (
        f"{_fmt(minx, precision)} {_fmt(miny, precision)} {_fmt(w, precision)} "
        f"{_fmt(h, precision)}"
    )

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        "<svg xmlns=\"http://www.w3.org/2000/svg\" version=\"1.1\" "
        f"viewBox=\"{view_box}\"{svg_w_attr}{svg_h_attr}>"
    )

    if title:
        # Keep it short; SVG title is helpful in editors.
        safe_title = (
            title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        lines.append(f"  <title>{safe_title}</title>")

    if background and background.lower() != "none":
        # Background rect in viewBox coordinates.
        lines.append(
            f'  <rect x="{_fmt(minx, precision)}" y="{_fmt(miny, precision)}" '
            f'width="{_fmt(w, precision)}" height="{_fmt(h, precision)}" '
            f'fill="{background}" />'
        )

    style_attr = (
        f'stroke="{style.stroke}" stroke-width="{_fmt(style.stroke_width, precision)}" '
        f'fill="{style.fill}" stroke-linecap="{style.stroke_linecap}" '
        f'stroke-linejoin="{style.stroke_linejoin}"'
    )

    if flip_y:
        # Flip around the center line: easiest is to apply a transform that scales y
        # by -1.
        # Since viewBox is in absolute coordinates, we flip about y = (miny + maxy).
        # That is: translate(0, miny+maxy) scale(1,-1)
        flip_y_line = _fmt(miny + maxy, precision)
        lines.append(f'  <g transform="translate(0,{flip_y_line}) scale(1,-1)">')
        indent = "    "
    else:
        indent = "  "

    for pl in polylines:
        pts = " ".join(f"{_fmt(x, precision)},{_fmt(y, precision)}" for x, y in pl)
        lines.append(f'{indent}<polyline points="{pts}" {style_attr} />')

    if flip_y:
        lines.append("  </g>")

    lines.append("</svg>")

    _ensure_parent_dir(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


# -------------------------
# Config parsing
# -------------------------


def parse_config(obj: dict[str, Any]) -> RenderConfig:
    obj = _as_dict(obj, "root")

    name = _as_str(obj.get("name", "L-System"), "name")
    axiom = _as_str(obj.get("axiom", ""), "axiom")
    _require(len(axiom) > 0, "axiom must be non-empty")

    iterations = _as_int(obj.get("iterations", 0), "iterations")
    _require(iterations >= 0, "iterations must be >= 0")

    rules_obj = _as_dict(obj.get("rules", {}), "rules")
    rules: dict[str, str] = {}
    for k, v in rules_obj.items():
        _require(
            isinstance(k, str) and len(k) == 1,
            "rules keys must be single-character strings",
        )
        rules[k] = _as_str(v, f"rules['{k}']")

    turtle = _as_dict(obj.get("turtle", {}), "turtle")
    angle_deg = _as_float(turtle.get("angle", 90), "turtle.angle")
    step = _as_float(turtle.get("step", 10), "turtle.step")

    start_obj = _as_dict(turtle.get("start", {}), "turtle.start")
    start = TurtleState(
        x=_as_float(start_obj.get("x", 0), "turtle.start.x"),
        y=_as_float(start_obj.get("y", 0), "turtle.start.y"),
        heading_deg=_as_float(start_obj.get("heading", 0), "turtle.start.heading"),
    )

    commands_obj = _as_dict(turtle.get("commands", {}), "turtle.commands")
    commands: dict[str, dict[str, Any]] = {}
    for sym, action in commands_obj.items():
        _require(
            isinstance(sym, str) and len(sym) == 1,
            "turtle.commands keys must be single-character strings",
        )
        commands[sym] = _as_dict(action, f"turtle.commands['{sym}']")

    svg = _as_dict(obj.get("svg", {}), "svg")
    margin = _as_float(svg.get("margin", 10), "svg.margin")
    precision = _as_int(svg.get("precision", 3), "svg.precision")
    _require(0 <= precision <= 10, "svg.precision must be between 0 and 10")
    flip_y = _as_bool(svg.get("flip_y", True), "svg.flip_y")

    width = svg.get("width")
    height = svg.get("height")
    if width is not None:
        width = _as_float(width, "svg.width")
        _require(width > 0, "svg.width must be > 0")
    if height is not None:
        height = _as_float(height, "svg.height")
        _require(height > 0, "svg.height must be > 0")

    style_obj = _as_dict(svg.get("style", {}), "svg.style")
    style = SvgStyle(
        stroke=_as_str(style_obj.get("stroke", "#000"), "svg.style.stroke"),
        stroke_width=_as_float(
            style_obj.get("stroke_width", 1.0), "svg.style.stroke_width"
        ),
        fill=_as_str(style_obj.get("fill", "none"), "svg.style.fill"),
        stroke_linecap=_as_str(
            style_obj.get("stroke_linecap", "round"), "svg.style.stroke_linecap"
        ),
        stroke_linejoin=_as_str(
            style_obj.get("stroke_linejoin", "round"), "svg.style.stroke_linejoin"
        ),
    )

    background = svg.get("background")
    if background is not None:
        background = _as_str(background, "svg.background")

    return RenderConfig(
        name=name,
        axiom=axiom,
        iterations=iterations,
        rules=rules,
        angle_deg=angle_deg,
        step=step,
        start=start,
        commands=commands,
        margin=margin,
        precision=precision,
        flip_y=flip_y,
        width=width,
        height=height,
        style=style,
        background=background,
    )


def load_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        try:
            return cast(dict[str, Any], json.load(f))
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in {path}: {e}") from e


# -------------------------
# Random config generator
# -------------------------


def _random_balanced_word(
    rng: random.Random, length: int, *, p_branch: float = 0.20
) -> str:
    """Generate a random L-system replacement word with balanced brackets.

    Produces symbols from: F, +, -, [, ]
    Ensures brackets are balanced and never go negative.
    """
    word: list[str] = []
    depth = 0

    for _ in range(length):
        r = rng.random()
        if r < p_branch and depth < 3:
            word.append("[")
            depth += 1
            continue
        # When depth == 0 this branch is always False, so the p_branch * 2
        # probability mass for ']' falls through to the forward/turn choices
        # below — intentionally making branching symbols rarer at the root.
        if r < p_branch * 2 and depth > 0:
            word.append("]")
            depth -= 1
            continue

        # turns vs forward
        t = rng.random()
        if t < 0.55:
            word.append("F")
        elif t < 0.775:
            word.append("+")
        else:
            word.append("-")

    # close remaining brackets
    word.extend("]" * depth)

    # ensure at least one F
    if "F" not in word:
        word.append("F")

    return "".join(word)


def generate_random_config(seed: int | None = None) -> dict[str, Any]:
    rng = random.Random(seed)

    angle = rng.choice([15, 20, 22.5, 25, 30, 36, 45, 60, 90])
    iterations = rng.randint(3, 6)
    step = rng.choice([5, 8, 10, 12, 15])

    # Build a simple plant-ish system with one or two rewriting symbols.
    # We'll keep it relatively simple and always provide a command table.
    use_x = rng.random() < 0.5

    if use_x:
        axiom = "X"
        rule_f = _random_balanced_word(rng, rng.randint(8, 18))
        # X expands to a mix of F, X and branching with some probability
        x_parts = []
        for _ in range(rng.randint(3, 6)):
            roll = rng.random()
            if roll < 0.45:
                x_parts.append("F")
            elif roll < 0.65:
                x_parts.append("X")
            elif roll < 0.80:
                x_parts.append("+")
            elif roll < 0.95:
                x_parts.append("-")
            else:
                x_parts.append("[X]")
        rule_x = "".join(x_parts)
        rules = {"F": rule_f, "X": rule_x}
    else:
        axiom = "F"
        rules = {"F": _random_balanced_word(rng, rng.randint(10, 22))}

    cfg = {
        "name": "Random L-System",
        "axiom": axiom,
        "iterations": iterations,
        "rules": rules,
        "turtle": {
            "angle": angle,
            "step": step,
            "start": {"x": 0, "y": 0, "heading": 90},
            "commands": {
                "F": {"type": "forward", "draw": True},
                "f": {"type": "forward", "draw": False},
                "+": {"type": "turn", "direction": +1, "angle": 1},
                "-": {"type": "turn", "direction": -1, "angle": 1},
                "[": {"type": "push"},
                "]": {"type": "pop"},
                "X": {"type": "noop"},
            },
        },
        "svg": {
            "margin": 10,
            "precision": 3,
            "flip_y": True,
            "style": {
                "stroke": "#000",
                "stroke_width": 1.0,
                "fill": "none",
                "stroke_linecap": "round",
                "stroke_linejoin": "round",
            },
        },
    }

    # Internal sanity check: generated config must always parse cleanly.
    parse_config(cfg)
    return cfg


def dump_json(obj: dict[str, Any], path: str) -> None:
    _ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


# -------------------------
# CLI / Help
# -------------------------

HELP_EPILOG = r"""
INPUT JSON SYNTAX (render)

The renderer consumes a single JSON file describing:
  - an L-system (axiom, rules, iterations)
  - a turtle interpretation (angle/step/start + a command table)
  - SVG output options (style, margin, viewBox behavior)

Top-level keys

  name: string (optional)
      A human-readable title; written into the SVG <title>.

  axiom: string (required)
      The initial word.

  iterations: integer >= 0 (required)
      Number of rewriting steps.

  rules: object mapping single-character string -> string (optional)
      Production rules. Each key must be a single character.
      Symbols without a rule rewrite to themselves.

  turtle: object (optional)
      Controls how symbols are interpreted geometrically.

    turtle.angle: number (default 90)
        Base turn angle, in degrees.

    turtle.step: number (default 10)
        Base forward step length.

    turtle.start: object (optional)
        Starting turtle state.

        turtle.start.x: number (default 0)
        turtle.start.y: number (default 0)
        turtle.start.heading: number degrees (default 0)
            Heading direction; 0 = +X, 90 = +Y.

    turtle.commands: object mapping single-character symbol -> action object (optional)
        Command table. If a symbol is not present here, the interpreter uses a default:
            default_action = "forward_draw"
        i.e. unknown symbols behave like a drawing forward step.

        Action objects

          1) Forward
             { "type": "forward", "draw": true|false, "step": <number optional> }

             - Moves the turtle forward by turtle.step * step
             - If draw=true: extends the current polyline
             - If draw=false: performs a pen-up move and starts a new polyline

          2) Turn (relative)
             { "type": "turn", "direction": +1|-1, "angle": <number optional> }

             - Rotates heading by direction * angle * turtle.angle
             - angle defaults to 1

          3) Turn (absolute increment)
             { "type": "turn_abs", "angle": <number degrees> }

             - Adds an absolute degree value to the heading.
             - Useful for special rotations like 180-degree turns.

          4) Branching
             { "type": "push" }
             { "type": "pop" }

             - push saves current (x,y,heading) on a stack
             - pop restores the last saved state
             - on pop, a new polyline is started at the restored position to avoid
               unintended connecting strokes

          5) No-op
             { "type": "noop" }

SVG options

  svg: object (optional)

    svg.margin: number (default 10)
        Extra margin added to the computed bounds (in the same units as turtle.step).

    svg.precision: integer 0..10 (default 3)
        Coordinate formatting precision.

    svg.flip_y: boolean (default true)
        If true, wraps the drawing in a group transform that flips the Y-axis.
        This keeps turtle math in a standard Cartesian coordinate system.

    svg.width / svg.height: number (optional)
        If set, specifies explicit SVG width/height attributes (viewBox is still used).

    svg.background: string color (optional)
        Adds a background rect. Example: "white" or "#fff". Use "none" (default)
        to omit.

    svg.style: object (optional)
        style.stroke: string (default "#000")
        style.stroke_width: number (default 1)
        style.fill: string (default "none")
        style.stroke_linecap: string (default "round")
        style.stroke_linejoin: string (default "round")

Examples

  Minimal (Koch curve):

    {
      "axiom": "F",
      "iterations": 4,
      "rules": {"F": "F+F--F+F"},
      "turtle": {
        "angle": 60,
        "step": 10,
        "commands": {
          "F": {"type": "forward", "draw": true},
          "+": {"type": "turn", "direction": +1},
          "-": {"type": "turn", "direction": -1}
        }
      }
    }

RANDOM INPUT GENERATION (random)

  python lsystem_generator.py random out.json --seed 123

Produces a small JSON config intended for experimentation. These configs are not
meant to be mathematically "nice"; they are meant to be quick to tweak.
"""


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lsystem_generator.py",
        description="Streaming L-system renderer that outputs SVG.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser(
        "render",
        help="Render an L-system JSON config to an SVG file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pr.add_argument("config", help="Path to the input JSON config.")
    pr.add_argument("output", help="Path to write the SVG output.")
    pr.add_argument(
        "--default-action",
        choices=["forward_draw", "forward_move", "noop"],
        default="forward_draw",
        help=(
            "What to do for symbols not found in turtle.commands. "
            "Default: forward_draw (unknown symbols draw forward)."
        ),
    )

    pv = sub.add_parser(
        "validate",
        help="Validate a JSON config and print a brief summary.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pv.add_argument("config", help="Path to the input JSON config.")

    pg = sub.add_parser(
        "random",
        help="Generate a random JSON config for experimentation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pg.add_argument("output", help="Where to write the generated JSON file.")
    pg.add_argument(
        "--seed", type=int, default=None, help="Seed for repeatable randomness."
    )

    return p


# -------------------------
# Commands
# -------------------------


def cmd_render(
    config_path: str, output_path: str, default_action: _DefaultAction
) -> None:
    cfg_obj = load_json(config_path)
    cfg = parse_config(cfg_obj)

    symbols = stream_expand(cfg.axiom, cfg.rules, cfg.iterations)
    polylines = interpret_to_polylines(
        symbols,
        commands=cfg.commands,
        angle_deg=cfg.angle_deg,
        step=cfg.step,
        start=cfg.start,
        default_action=default_action,
    )

    write_svg(
        polylines,
        out_path=output_path,
        margin=cfg.margin,
        precision=cfg.precision,
        flip_y=cfg.flip_y,
        width=cfg.width,
        height=cfg.height,
        style=cfg.style,
        background=cfg.background,
        title=cfg.name,
    )


_VALIDATE_SYMBOL_LIMIT = 10_000


def cmd_validate(config_path: str) -> None:
    cfg_obj = load_json(config_path)
    cfg = parse_config(cfg_obj)

    print(f"name: {cfg.name}")
    print(f"axiom length: {len(cfg.axiom)}")
    print(f"iterations: {cfg.iterations}")
    print(f"rules: {len(cfg.rules)}")
    print(
        "turtle: "
        f"angle={cfg.angle_deg} step={cfg.step} "
        f"start=({cfg.start.x},{cfg.start.y},{cfg.start.heading_deg}deg)"
    )
    print(f"commands: {len(cfg.commands)}")
    print(f"svg: margin={cfg.margin} precision={cfg.precision} flip_y={cfg.flip_y}")

    # Run a bounded expansion + interpretation to catch render-time failures
    # (e.g. no drawable geometry, bad command definitions, exponential blow-up).
    raw = stream_expand(cfg.axiom, cfg.rules, cfg.iterations)
    bounded = list(itertools.islice(raw, _VALIDATE_SYMBOL_LIMIT))
    truncated = len(bounded) == _VALIDATE_SYMBOL_LIMIT
    polylines = interpret_to_polylines(
        bounded,
        commands=cfg.commands,
        angle_deg=cfg.angle_deg,
        step=cfg.step,
        start=cfg.start,
        default_action="forward_draw",
    )
    sym_label = f"{len(bounded)}+" if truncated else str(len(bounded))
    print(f"symbols (sampled): {sym_label}")
    print(f"polylines: {len(polylines)}")
    if truncated:
        print(
            f"warning: expansion exceeds {_VALIDATE_SYMBOL_LIMIT} symbols; "
            "geometry stats are based on the first portion only"
        )
    if not polylines:
        raise ConfigError("Config produces no drawable geometry")


def cmd_random(output_path: str, seed: int | None) -> None:
    cfg = generate_random_config(seed)
    dump_json(cfg, output_path)


def main(argv: list[str] | None = None) -> int:
    ap = build_argparser()
    args = ap.parse_args(argv)

    try:
        if args.cmd == "render":
            cmd_render(
                args.config, args.output, cast(_DefaultAction, args.default_action)
            )
        elif args.cmd == "validate":
            cmd_validate(args.config)
        elif args.cmd == "random":
            cmd_random(args.output, args.seed)
        else:
            raise AssertionError("unreachable")
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"File error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
