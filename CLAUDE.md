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
pytest
python lsystem_generator.py validate <config.json>
python lsystem_generator.py render <config.json> <output.svg>
python lsystem_generator.py random <output.json> [--seed N]
ruff check .
ruff check . --fix
mypy .
```

## Key constraints

- **Python 3.11+**; stdlib only — no external dependencies.
- Keep the 3 phases independent: Grammar expansion → Turtle → SVG (see AGENTS.md).
- JSON config changes must be backward-compatible; see AGENTS.md for rules.
- See `example/` for 20+ working configs to test against.
- `validate` runs a bounded geometry pass (≤ 10 000 symbols); keep that limit in `_VALIDATE_SYMBOL_LIMIT`.
