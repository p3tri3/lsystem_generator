# CLAUDE.md

Guidance for **Claude Code** in this repository.

## Canonical instructions

Repository-wide, stable agent rules live in **AGENTS.md**.
Treat **AGENTS.md as the source of truth** for architecture, invariants, and validation.

## Claude-specific preferences (keep lightweight)

- Make a short plan and apply incremental edits (small diffs).
- When changing behavior, add/adjust unit tests in the same change.
- Avoid speculative refactors unless requested.

## Handy commands

```bash
python -m unittest test_lsystem_generator.py
python lsystem_generator.py validate <config.json>
python lsystem_generator.py render <config.json> <output.svg>
```
