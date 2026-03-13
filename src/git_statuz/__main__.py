"""Module entry point for launching GitStatuz with ``python -m``."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
