#!/usr/bin/env python3
"""Compatibility launcher. Prefer the installed `jki` command."""
from jki.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
