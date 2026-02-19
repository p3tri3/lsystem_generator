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
    generate_random_config,
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


class TestEndToEnd(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
