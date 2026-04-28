"""beril-presentation-maker subcommand modules.

Each module exposes:
  - add_parser(subparsers) → argparse.ArgumentParser
  - run(args) → int (exit code)
"""
from beril_presentation_maker.commands import (  # noqa: F401
    assemble,
    configure,
    continue_run,
    draft,
    install_skill,
)
