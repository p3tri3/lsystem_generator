#!/usr/bin/env python3
import unittest
import math
import tempfile
import os
import json
from lsystem_generator import (
    parse_config,
    RenderConfig,
    ConfigError,
    stream_expand,
    interpret_to_polylines,
    TurtleState,
    SvgStyle,
    write_svg,
    compute_bounds,
    load_json,
    generate_random_config,
    main,
)


class TestConfigParsing(unittest.TestCase):
    def test_basic_config(self):
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
        self.assertIsInstance(config, RenderConfig)
        self.assertEqual(config.axiom, "F")
        self.assertEqual(config.iterations, 1)
        self.assertEqual(config.rules["F"], "F+F")
        self.assertEqual(config.angle_deg, 90)
        self.assertEqual(config.step, 10)

    def test_missing_required_fields(self):
        # Missing axiom
        with self.assertRaises(ConfigError):
            parse_config({"iterations": 1, "turtle": {}, "svg": {}})

        # Missing iterations - Code defaults to 0, so this should NOT raise
        config = parse_config({"axiom": "F", "turtle": {}, "svg": {}})
        self.assertEqual(config.iterations, 0)

    def test_invalid_types(self):
        # Invalid iterations type
        with self.assertRaises(ConfigError):
            parse_config({"axiom": "F", "iterations": "1", "turtle": {}, "svg": {}})

    def test_multichar_rule_key(self):
        with self.assertRaises(ConfigError):
            parse_config({"axiom": "F", "rules": {"FF": "F"}, "turtle": {}, "svg": {}})

    def test_precision_out_of_range(self):
        with self.assertRaises(ConfigError):
            parse_config({"axiom": "F", "turtle": {}, "svg": {"precision": 15}})


class TestExpansion(unittest.TestCase):
    def test_simple_expansion(self):
        # Algae: A -> AB, B -> A
        rules = {"A": "AB", "B": "A"}
        axiom = "A"

        # n=0: A
        gen0 = list(stream_expand(axiom, rules, 0))
        self.assertEqual("".join(gen0), "A")

        # n=1: AB
        gen1 = list(stream_expand(axiom, rules, 1))
        self.assertEqual("".join(gen1), "AB")

        # n=2: ABA
        gen2 = list(stream_expand(axiom, rules, 2))
        self.assertEqual("".join(gen2), "ABA")

        # n=3: ABAAB
        gen3 = list(stream_expand(axiom, rules, 3))
        self.assertEqual("".join(gen3), "ABAAB")

    def test_no_rules(self):
        # If no rules match, symbols should remain unchanged
        rules = {}
        axiom = "F+-F"
        gen = list(stream_expand(axiom, rules, 5))
        self.assertEqual("".join(gen), "F+-F")

    def test_zero_iterations_with_rules(self):
        # At iterations=0 the axiom must pass through unchanged even when rules exist
        rules = {"F": "F+F", "X": "FF"}
        self.assertEqual("".join(stream_expand("FX", rules, 0)), "FX")


class TestTurtle(unittest.TestCase):
    def setUp(self):
        self.start = TurtleState(x=0, y=0, heading_deg=0)
        # Note: interpret_to_polylines takes command dicts, not full objects
        self.commands = {
            "F": {"type": "forward", "draw": True},
            "f": {"type": "forward", "draw": False},
            "+": {"type": "turn", "direction": 1},
            "-": {"type": "turn", "direction": -1},
            "[": {"type": "push"},
            "]": {"type": "pop"},
        }
        self.angle = 90
        self.step = 10

    def test_forward_draw(self):
        # Move forward 10 units along +X (heading 0)
        # We need to iterate over the generator if interpret_to_polylines expects an iterable of symbols
        # But interpret_to_polylines expects `symbols: Iterable[str]`. A string is iterable.
        polylines = interpret_to_polylines(
            "F",
            commands=self.commands,
            angle_deg=self.angle,
            step=self.step,
            start=self.start,
            default_action="noop",
        )
        # Expect [(0,0), (10,0)]
        self.assertEqual(len(polylines), 1)
        p0 = polylines[0][0]
        p1 = polylines[0][1]

        self.assertAlmostEqual(p0[0], 0)
        self.assertAlmostEqual(p0[1], 0)
        self.assertAlmostEqual(p1[0], 10)
        self.assertAlmostEqual(p1[1], 0)

    def test_branching(self):
        # F[+F]F
        # interpret_to_polylines handles the stack logic

        polylines = interpret_to_polylines(
            "F[+F]F",
            commands=self.commands,
            angle_deg=self.angle,
            step=self.step,
            start=self.start,
        )

        # We expect separate polylines for disjoint segments or after pops
        # 1. F (trunk)
        # 2. [ push
        # 3. + turn
        # 4. F (branch)
        # 5. ] pop -> new polyline started at restore point
        # 6. F (trunk continuation)

        # Currently, lsystem_generator.py logic:
        # - start_new called on pop
        # - start_new called on forward_move (draw=False)
        # - if draw=True, adds to current polyline

        # So:
        # 1. Start new polyline at (0,0)
        # 2. F -> extends to (10,0). Polyline: [(0,0), (10,0)]
        # 3. [ -> push
        # 4. + -> turn
        # 5. F -> extends to (10,10). Polyline: [(0,0), (10,0), (10,10)]  <-- WAIT, branching should usually start new polyline?
        # Let's check the code for `push`. It just appends to stack. It DOES NOT start a new polyline.
        # But `pop` DOES start a new polyline.
        # So "F[+F]" would be one polyline [(0,0), (10,0), (10,10)].
        # Then "]" pops and STARTS NEW POLYLINE at (10,0).
        # Then "F" extends that new polyline to (20,0).

        # So we expect 2 polylines:
        # 1. [(0,0), (10,0), (10,10)]
        # 2. [(10,0), (20,0)]

        self.assertEqual(len(polylines), 2)

        # Verify coordinates of first polyline
        pl1 = polylines[0]
        self.assertEqual(len(pl1), 3)
        self.assertAlmostEqual(pl1[0][0], 0)
        self.assertAlmostEqual(pl1[0][1], 0)
        self.assertAlmostEqual(pl1[1][0], 10)
        self.assertAlmostEqual(pl1[1][1], 0)
        self.assertAlmostEqual(pl1[2][0], 10)
        self.assertAlmostEqual(
            pl1[2][1], 10
        )  # +90 deg is +Y? Let's check angle/direction conventions.
        # Code: h += direction * angle. direction=1 means +angle.
        # defaults: angle=90.
        # rad = deg * pi / 180.
        # nx = x + dist * cos(rad)
        # ny = y + dist * sin(rad)
        # so h=90 -> cos=0, sin=1 -> +y. Correct.

    def test_turn_abs(self):
        # turn_abs sets heading by adding an absolute angle delta
        commands = {
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
        self.assertEqual(len(polylines), 1)
        self.assertAlmostEqual(polylines[0][1][0], 0, places=9)
        self.assertAlmostEqual(polylines[0][1][1], 10, places=9)

    def test_forward_move_starts_new_polyline(self):
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
        self.assertEqual(len(polylines), 2)
        self.assertAlmostEqual(polylines[0][0][0], 0)
        self.assertAlmostEqual(polylines[0][-1][0], 10)
        self.assertAlmostEqual(polylines[1][0][0], 20)
        self.assertAlmostEqual(polylines[1][-1][0], 30)

    def test_pop_empty_stack(self):
        with self.assertRaises(ConfigError):
            interpret_to_polylines(
                "]",
                commands=self.commands,
                angle_deg=self.angle,
                step=self.step,
                start=self.start,
            )

    def test_invalid_default_action(self):
        with self.assertRaises(ConfigError):
            interpret_to_polylines(
                "F",
                commands=self.commands,
                angle_deg=self.angle,
                step=self.step,
                start=self.start,
                default_action="typo",  # type: ignore[arg-type]
            )

    def test_unknown_command_default(self):
        # 'X' is unknown. Default action is forward_draw
        polylines = interpret_to_polylines(
            "X",
            commands={},  # Empty commands
            angle_deg=90,
            step=10,
            start=self.start,
            default_action="forward_draw",
        )
        self.assertEqual(len(polylines), 1)
        self.assertAlmostEqual(polylines[0][1][0], 10)


class TestComputeBounds(unittest.TestCase):
    def test_basic_bounds(self):
        polylines = [[(0.0, 5.0), (10.0, -2.0)], [(3.0, 8.0), (7.0, 1.0)]]
        min_x, min_y, max_x, max_y = compute_bounds(polylines)
        self.assertAlmostEqual(min_x, 0.0)
        self.assertAlmostEqual(min_y, -2.0)
        self.assertAlmostEqual(max_x, 10.0)
        self.assertAlmostEqual(max_y, 8.0)

    def test_collinear_horizontal(self):
        # All points on the same horizontal line: height (y-span) is zero
        polylines = [[(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]]
        min_x, min_y, max_x, max_y = compute_bounds(polylines)
        self.assertAlmostEqual(min_y, 0.0)
        self.assertAlmostEqual(max_y, 0.0)
        self.assertAlmostEqual(max_x - min_x, 10.0)

    def test_empty_polylines_raises(self):
        with self.assertRaises(ConfigError):
            compute_bounds([])


class TestEndToEnd(unittest.TestCase):
    def _render(self, polylines, **kwargs):
        """Helper: write SVG to a temp file and return its content."""
        defaults = dict(
            margin=5,
            precision=2,
            flip_y=False,
            width=None,
            height=None,
            style=SvgStyle(),
            background=None,
        )
        defaults.update(kwargs)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "out.svg")
            write_svg(polylines, out_path=out_path, **defaults)
            with open(out_path) as f:
                return f.read()

    def test_write_svg(self):
        polylines = [[(0, 0), (10, 10)]]
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

            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r") as f:
                content = f.read()
                self.assertIn("<svg", content)
                # Precision 2 means 10.00 probably? Or formatted.
                # Code uses _fmt which strips trailing zeros.
                # So 10.00 -> 10.
                self.assertIn('points="0,0 10,10"', content)

    def test_write_svg_flip_y(self):
        content = self._render([[(0, 0), (10, 5)]], flip_y=True)
        self.assertIn('transform="translate(', content)
        self.assertIn("scale(1,-1)", content)

    def test_write_svg_background(self):
        content = self._render([[(0, 0), (10, 5)]], background="#ff0000")
        self.assertIn("<rect", content)
        self.assertIn('fill="#ff0000"', content)

    def test_write_svg_width_height(self):
        content = self._render([[(0, 0), (10, 5)]], width=200.0, height=100.0)
        self.assertIn('width="200"', content)
        self.assertIn('height="100"', content)

    def test_write_svg_title(self):
        content = self._render([[(0, 0), (10, 5)]], title="My <L-System>")
        self.assertIn("<title>", content)
        self.assertIn("My &lt;L-System&gt;", content)

    def test_random_generator(self):
        cfg = generate_random_config(seed=42)
        # Basic check that it produced a valid-looking dictionary
        self.assertIn("axiom", cfg)
        self.assertIn("rules", cfg)
        self.assertIn("turtle", cfg)
        self.assertIsInstance(cfg["iterations"], int)

        # Determinism check
        cfg2 = generate_random_config(seed=42)
        self.assertEqual(cfg, cfg2)


class TestLoadJson(unittest.TestCase):
    def test_malformed_json(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as tmp:
            tmp.write("{ not valid json }")
            tmp_path = tmp.name
        try:
            with self.assertRaises(ConfigError):
                load_json(tmp_path)
        finally:
            os.unlink(tmp_path)


_EXAMPLE_DIR = os.path.join(os.path.dirname(__file__), "example")


class TestCLI(unittest.TestCase):
    def test_validate_command(self):
        koch = os.path.join(_EXAMPLE_DIR, "koch.json")
        self.assertEqual(main(["validate", koch]), 0)

    def test_render_command(self):
        koch = os.path.join(_EXAMPLE_DIR, "koch.json")
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.svg")
            self.assertEqual(main(["render", koch, out]), 0)
            self.assertTrue(os.path.exists(out))

    def test_file_not_found_returns_error_code(self):
        self.assertEqual(main(["render", "nonexistent_config.json", "out.svg"]), 2)

    def test_invalid_config_returns_error_code(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as tmp:
            json.dump({"axiom": "F", "iterations": "bad", "turtle": {}, "svg": {}}, tmp)
            tmp_path = tmp.name
        try:
            self.assertEqual(main(["validate", tmp_path]), 2)
        finally:
            os.unlink(tmp_path)


class TestExampleConfigs(unittest.TestCase):
    """Regression tests: every example config must render without error."""

    def _render_example(self, filename: str) -> str:
        """Parse, expand, interpret, and write SVG; return SVG content."""
        from lsystem_generator import stream_expand, interpret_to_polylines

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

    def test_koch(self):
        content = self._render_example("koch.json")
        self.assertIn("<svg", content)
        self.assertIn("<polyline", content)
        self.assertIn("viewBox=", content)

    def test_fractal_tree(self):
        content = self._render_example("fractal_tree.json")
        self.assertIn("<svg", content)
        self.assertIn("<polyline", content)

    def test_hilbert_curve(self):
        content = self._render_example("hilbert_curve.json")
        self.assertIn("<svg", content)
        self.assertIn("<polyline", content)


if __name__ == "__main__":
    unittest.main()
