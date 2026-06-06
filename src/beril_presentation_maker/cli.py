"""`beril-presentation-maker` top-level CLI entry point.

Dispatches to command modules under beril_presentation_maker.commands/.

Subcommands:
  install-skill   Copy shipped skill/ tree into BERIL/.claude/skills/beril-presentation-maker/.
  configure       Verify claude is on PATH; report optional dep status.
  draft           Start a fresh presentation draft (full 14-stage pipeline).
  continue        Resume a draft from a named stage (--resume-from).
  assemble        Render slide_spec.json to .pptx (and optionally .pdf).
  prune           Prune old drafts under projects/<id>/talks/ (v0.3.4.1).

The drafting workflow runs via the shipped shell script
tools/presentation_maker.sh, invoked by the `draft` and `continue`
Python subcommands. Same pattern as beril-paper-writer / beril-adversarial.

Exit codes:
  0  success
  1  user error (bad args, missing draft_dir, missing file user should fix)
  2  runtime error (subprocess failed, package data missing)
  3  config error (claude not installed; tools unavailable)
"""

from __future__ import annotations

import argparse
import sys

from beril_presentation_maker import __version__
from beril_presentation_maker.commands import (
    assemble,
    configure,
    continue_run,
    draft,
    install_skill,
    prune,
    template_env,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="beril-presentation-maker",
        description=(
            "BERIL Presentation Maker — drafts evidence-grounded scientific "
            "presentations (talks + posters) from BERDL analysis projects, "
            "in KBase brand. See "
            "https://github.com/ArkinLaboratory/beril-presentation-maker-skill."
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"beril-presentation-maker-skill {__version__}",
    )
    subparsers = p.add_subparsers(dest="command", metavar="<command>")

    install_skill.add_parser(subparsers)
    configure.add_parser(subparsers)
    template_env.add_parser(subparsers)
    draft.add_parser(subparsers)
    continue_run.add_parser(subparsers)
    assemble.add_parser(subparsers)
    prune.add_parser(subparsers)

    return p


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)

    parser = build_parser()
    args = parser.parse_args(raw_argv)

    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
