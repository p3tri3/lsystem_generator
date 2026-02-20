#!/usr/bin/env python3
import io
import json
import os
import tempfile
from contextlib import redirect_stderr
from typing import Any

import pytest

from lsystem_generator import (
    ConfigError,
    Point,
    RenderConfig,
    SvgStyle,
    TurtleState,
    compute_bounds,
    generate_random_config,
    interpret_to_polylines,
    load_json,
    main,
    parse_config,
    stream_expand,
    write_svg,
)


class TestConfigParsing:
    def test_basic_config(self) -> None:
        config_data = {
            "axiom": "F",
            "iterations": 1,
            "rules": {"F": "F+F"},
            "turtle": {
                "angle": 90,
                "step": 10,
                "start": {"x": 0, "y": 0, "heading": 0},
                "commands": {"F": {"type": "forward", "draw": True, "step": 1}},
            },
            "svg": {
                "margin": 5,
                "precision": 2,
                "flip_y": True,
                "style": {"stroke": "#000", "stroke_width": 1},
            },
        }
        config = parse_config(config_data)
        assert isinstance(config, RenderConfig)
        assert config.axiom == "F"
        assert config.iterations == 1
        assert config.rules["F"] == "F+F"
        assert config.angle_deg == 90
        assert config.step == 10

    def test_missing_required_fields(self) -> None:
        # Missing axiom
        with pytest.raises(ConfigError):
            parse_config({"iterations": 1, "turtle": {}, "svg": {}})

        # Missing iterations - Code defaults to 0, so this should NOT raise
        config = parse_config({"axiom": "F", "turtle": {}, "svg": {}})
        assert config.iterations == 0

    def test_invalid_types(self) -> None:
        # Invalid iterations type
        with pytest.raises(ConfigError):
            parse_config({"axiom": "F", "iterations": "1", "turtle": {}, "svg": {}})

    def test_multichar_rule_key(self) -> None:
        with pytest.raises(ConfigError):
            parse_config({"axiom": "F", "rules": {"FF": "F"}, "turtle": {}, "svg": {}})

    def test_precision_out_of_range(self) -> None:
        with pytest.raises(ConfigError):
            parse_config({"axiom": "F", "turtle": {}, "svg": {"precision": 15}})


class TestExpansion:
    def test_simple_expansion(self) -> None:
        # Algae: A -> AB, B -> A
        rules = {"A": "AB", "B": "A"}
        axiom = "A"

        # n=0: A
        gen0 = list(stream_expand(axiom, rules, 0))
        assert "".join(gen0) == "A"

        # n=1: AB
        gen1 = list(stream_expand(axiom, rules, 1))
        assert "".join(gen1) == "AB"

        # n=2: ABA
        gen2 = list(stream_expand(axiom, rules, 2))
        assert "".join(gen2) == "ABA"

        # n=3: ABAAB
        gen3 = list(stream_expand(axiom, rules, 3))
        assert "".join(gen3) == "ABAAB"

    def test_no_rules(self) -> None:
        # If no rules match, symbols should remain unchanged
        rules: dict[str, str] = {}
        axiom = "F+-F"
        gen = list(stream_expand(axiom, rules, 5))
        assert "".join(gen) == "F+-F"

    def test_zero_iterations_with_rules(self) -> None:
        # At iterations=0 the axiom must pass through unchanged even when rules exist
        rules = {"F": "F+F", "X": "FF"}
        assert "".join(stream_expand("FX", rules, 0)) == "FX"


class TestTurtle:
    def setup_method(self) -> None:
        self.start = TurtleState(x=0, y=0, heading_deg=0)
        self.commands: dict[str, dict[str, Any]] = {
            "F": {"type": "forward", "draw": True},
            "f": {"type": "forward", "draw": False},
            "+": {"type": "turn", "direction": 1},
            "-": {"type": "turn", "direction": -1},
            "[": {"type": "push"},
            "]": {"type": "pop"},
        }
        self.angle = 90
        self.step = 10

    def test_forward_draw(self) -> None:
        # Move forward 10 units along +X (heading 0)
        polylines = interpret_to_polylines(
            "F",
            commands=self.commands,
            angle_deg=self.angle,
            step=self.step,
            start=self.start,
            default_action="noop",
        )
        # Expect [(0,0), (10,0)]
        assert len(polylines) == 1
        p0 = polylines[0][0]
        p1 = polylines[0][1]

        assert p0[0] == pytest.approx(0)
        assert p0[1] == pytest.approx(0)
        assert p1[0] == pytest.approx(10)
        assert p1[1] == pytest.approx(0)

    def test_branching(self) -> None:
        # F[+F]F
        polylines = interpret_to_polylines(
            "F[+F]F",
            commands=self.commands,
            angle_deg=self.angle,
            step=self.step,
            start=self.start,
        )

        # So:
        # 1. Start new polyline at (0,0)
        # 2. F -> extends to (10,0). Polyline: [(0,0), (10,0)]
        # 3. [ -> push
        # 4. + -> turn
        # 5. F -> extends to (10,10). Polyline: [(0,0), (10,0), (10,10)]
        # Then "]" pops and STARTS NEW POLYLINE at (10,0).
        # Then "F" extends that new polyline to (20,0).

        # So we expect 2 polylines:
        # 1. [(0,0), (10,0), (10,10)]
        # 2. [(10,0), (20,0)]

        assert len(polylines) == 2

        # Verify coordinates of first polyline
        pl1 = polylines[0]
        assert len(pl1) == 3
        assert pl1[0][0] == pytest.approx(0)
        assert pl1[0][1] == pytest.approx(0)
        assert pl1[1][0] == pytest.approx(10)
        assert pl1[1][1] == pytest.approx(0)
        assert pl1[2][0] == pytest.approx(10)
        assert pl1[2][1] == pytest.approx(10)

    def test_turn_abs(self) -> None:
        # turn_abs sets heading by adding an absolute angle delta
        commands: dict[str, dict[str, Any]] = {
            "A": {"type": "turn_abs", "angle": 90},
            "F": {"type": "forward", "draw": True},
        }
        polylines = interpret_to_polylines(
            "AF",
            commands=commands,
            angle_deg=45,
            step=10,
            start=self.start,
        )
        # heading starts at 0; turn_abs adds 90 → heading = 90
        # forward: (0 + 10*cos(90°), 0 + 10*sin(90°)) ≈ (0, 10)
        assert len(polylines) == 1
        assert polylines[0][1][0] == pytest.approx(0, abs=1e-9)
        assert polylines[0][1][1] == pytest.approx(10, abs=1e-9)

    def test_forward_move_starts_new_polyline(self) -> None:
        # Pen-up (draw=False) moves without drawing and starts a new polyline.
        # "FfF": draw→(10,0), move→(20,0), draw→(30,0) gives 2 polylines.
        polylines = interpret_to_polylines(
            "FfF",
            commands=self.commands,
            angle_deg=self.angle,
            step=self.step,
            start=self.start,
            default_action="noop",
        )
        assert len(polylines) == 2
        assert polylines[0][0][0] == pytest.approx(0)
        assert polylines[0][-1][0] == pytest.approx(10)
        assert polylines[1][0][0] == pytest.approx(20)
        assert polylines[1][-1][0] == pytest.approx(30)

    def test_pop_empty_stack(self) -> None:
        with pytest.raises(ConfigError):
            interpret_to_polylines(
                "]",
                commands=self.commands,
                angle_deg=self.angle,
                step=self.step,
                start=self.start,
            )

    def test_invalid_default_action(self) -> None:
        with pytest.raises(ConfigError):
            interpret_to_polylines(
                "F",
                commands=self.commands,
                angle_deg=self.angle,
                step=self.step,
                start=self.start,
                default_action="typo",  # type: ignore[arg-type]
            )

    def test_unknown_command_default(self) -> None:
        # 'X' is unknown. Default action is forward_draw
        polylines = interpret_to_polylines(
            "X",
            commands={},  # Empty commands
            angle_deg=90,
            step=10,
            start=self.start,
            default_action="forward_draw",
        )
        assert len(polylines) == 1
        assert polylines[0][1][0] == pytest.approx(10)


class TestComputeBounds:
    def test_basic_bounds(self) -> None:
        polylines = [[(0.0, 5.0), (10.0, -2.0)], [(3.0, 8.0), (7.0, 1.0)]]
        min_x, min_y, max_x, max_y = compute_bounds(polylines)
        assert min_x == pytest.approx(0.0)
        assert min_y == pytest.approx(-2.0)
        assert max_x == pytest.approx(10.0)
        assert max_y == pytest.approx(8.0)

    def test_collinear_horizontal(self) -> None:
        # All points on the same horizontal line: height (y-span) is zero
        polylines = [[(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]]
        min_x, min_y, max_x, max_y = compute_bounds(polylines)
        assert min_y == pytest.approx(0.0)
        assert max_y == pytest.approx(0.0)
        assert (max_x - min_x) == pytest.approx(10.0)

    def test_empty_polylines_raises(self) -> None:
        with pytest.raises(ConfigError):
            compute_bounds([])


class TestEndToEnd:
    def _render(
        self,
        polylines: list[list[Point]],
        *,
        margin: float = 5,
        precision: int = 2,
        flip_y: bool = False,
        width: float | None = None,
        height: float | None = None,
        style: SvgStyle | None = None,
        background: str | None = None,
        title: str | None = None,
    ) -> str:
        """Helper: write SVG to a temp file and return its content."""
        if style is None:
            style = SvgStyle()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "out.svg")
            write_svg(
                polylines,
                out_path=out_path,
                margin=margin,
                precision=precision,
                flip_y=flip_y,
                width=width,
                height=height,
                style=style,
                background=background,
                title=title,
            )
            with open(out_path) as f:
                return f.read()

    def test_write_svg(self) -> None:
        polylines: list[list[Point]] = [[(0.0, 0.0), (10.0, 10.0)]]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "test.svg")
            write_svg(
                polylines,
                out_path=out_path,
                margin=0,
                precision=2,
                flip_y=False,
                width=None,
                height=None,
                style=SvgStyle(),
                background=None,
            )

            assert os.path.exists(out_path)
            with open(out_path, "r") as f:
                content = f.read()
                assert "<svg" in content
                assert 'points="0,0 10,10"' in content

    def test_write_svg_flip_y(self) -> None:
        content = self._render([[(0.0, 0.0), (10.0, 5.0)]], flip_y=True)
        assert 'transform="translate(' in content
        assert "scale(1,-1)" in content

    def test_write_svg_background(self) -> None:
        content = self._render([[(0.0, 0.0), (10.0, 5.0)]], background="#ff0000")
        assert "<rect" in content
        assert 'fill="#ff0000"' in content

    def test_write_svg_width_height(self) -> None:
        content = self._render([[(0.0, 0.0), (10.0, 5.0)]], width=200.0, height=100.0)
        assert 'width="200"' in content
        assert 'height="100"' in content

    def test_write_svg_title(self) -> None:
        content = self._render([[(0.0, 0.0), (10.0, 5.0)]], title="My <L-System>")
        assert "<title>" in content
        assert "My &lt;L-System&gt;" in content

    def test_random_generator(self) -> None:
        cfg = generate_random_config(seed=42)
        assert "axiom" in cfg
        assert "rules" in cfg
        assert "turtle" in cfg
        assert isinstance(cfg["iterations"], int)

        # Determinism check
        cfg2 = generate_random_config(seed=42)
        assert cfg == cfg2


class TestLoadJson:
    def test_malformed_json(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tmp:
            tmp.write("{ not valid json }")
            tmp_path = tmp.name
        try:
            with pytest.raises(ConfigError):
                load_json(tmp_path)
        finally:
            os.unlink(tmp_path)


_EXAMPLE_DIR = os.path.join(os.path.dirname(__file__), "example")


class TestCLI:
    def test_validate_command(self) -> None:
        koch = os.path.join(_EXAMPLE_DIR, "koch.json")
        assert main(["validate", koch]) == 0

    def test_render_command(self) -> None:
        koch = os.path.join(_EXAMPLE_DIR, "koch.json")
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.svg")
            assert main(["render", koch, out]) == 0
            assert os.path.exists(out)

    def test_file_not_found_returns_error_code(self) -> None:
        with redirect_stderr(io.StringIO()):
            assert main(["render", "nonexistent_config.json", "out.svg"]) == 2

    def test_invalid_config_returns_error_code(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tmp:
            json.dump({"axiom": "F", "iterations": "bad", "turtle": {}, "svg": {}}, tmp)
            tmp_path = tmp.name
        try:
            with redirect_stderr(io.StringIO()):
                assert main(["validate", tmp_path]) == 2
        finally:
            os.unlink(tmp_path)


class TestExampleConfigs:
    """Regression tests: every example config must render without error."""

    def _render_example(self, filename: str) -> str:
        """Parse, expand, interpret, and write SVG; return SVG content."""
        path = os.path.join(_EXAMPLE_DIR, filename)
        cfg = parse_config(load_json(path))
        symbols = stream_expand(cfg.axiom, cfg.rules, cfg.iterations)
        polylines = interpret_to_polylines(
            symbols,
            commands=cfg.commands,
            angle_deg=cfg.angle_deg,
            step=cfg.step,
            start=cfg.start,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.svg")
            write_svg(
                polylines,
                out_path=out,
                margin=cfg.margin,
                precision=cfg.precision,
                flip_y=cfg.flip_y,
                width=cfg.width,
                height=cfg.height,
                style=cfg.style,
                background=cfg.background,
                title=cfg.name,
            )
            with open(out) as f:
                return f.read()

    def test_koch(self) -> None:
        content = self._render_example("koch.json")
        assert "<svg" in content
        assert "<polyline" in content
        assert "viewBox=" in content

    def test_fractal_tree(self) -> None:
        content = self._render_example("fractal_tree.json")
        assert "<svg" in content
        assert "<polyline" in content

    def test_hilbert_curve(self) -> None:
        content = self._render_example("hilbert_curve.json")
        assert "<svg" in content
        assert "<polyline" in content
