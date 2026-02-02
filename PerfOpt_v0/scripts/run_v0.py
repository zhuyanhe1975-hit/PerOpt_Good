#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""Thin wrapper to run the PerfOpt v0 CLI without requiring installation.

Keep this file small; implementation lives in perfopt.cli.run_v0_cli.
"""

from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    # Allow running from repo without installing the package.
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    from perfopt.cli.run_v0_cli import main as cli_main

    return int(cli_main(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
