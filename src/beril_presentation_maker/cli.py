"""beril-presentation-maker — command-line entry point.

v0.1.0-spec: stubs only. Each subcommand raises NotImplementedError
with a pointer to the SPEC/LAYOUT section that defines its behavior.
Implementation lands in subsequent commits per LAYOUT.md.

Mirrors beril_paper_writer.cli structure (argparse with sub-parsers,
console-script entry point in pyproject.toml).
"""
from __future__ import annotations

import argparse
import sys
from typing import NoReturn


def _stub(name: str, spec_section: str) -> NoReturn:
    msg = (
        f"beril-presentation-maker {name}: not implemented in v0.1.0-spec. "
        f"See SPEC.md {spec_section} for behavior; LAYOUT.md for shape."
    )
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def cmd_install_skill(args: argparse.Namespace) -> NoReturn:
    _stub("install-skill", "§14 Assembly + LAYOUT.md §1 Repository tree")


def cmd_configure(args: argparse.Namespace) -> NoReturn:
    _stub("configure", "§16 State machine + LAYOUT.md §3 CLI")


def cmd_continue_run(args: argparse.Namespace) -> NoReturn:
    _stub("continue", "§16.3 Resume semantics")


def cmd_assemble(args: argparse.Namespace) -> NoReturn:
    _stub("assemble", "§14 Assembly")


def cmd_revise(args: argparse.Namespace) -> NoReturn:
    _stub("revise", "§16.5 Targeted revision via revise")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="beril-presentation-maker",
        description=(
            "BERIL Presentation Maker — drafts evidence-grounded scientific "
            "presentations (talks + posters) from BERDL analysis projects."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version="beril-presentation-maker 0.1.0-spec",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install-skill", help="Install the Claude Code skill into a BERIL root.")
    p_install.add_argument("beril_root", nargs="?", default=None, help="Path to BERIL root (auto-detected if omitted).")
    p_install.add_argument("--force", action="store_true", help="Overwrite existing install.")
    p_install.set_defaults(func=cmd_install_skill)

    p_conf = sub.add_parser("configure", help="Verify environment, models, and sibling skills.")
    p_conf.set_defaults(func=cmd_configure)

    p_cont = sub.add_parser("continue", help="Resume a paused draft.")
    p_cont.add_argument("draft_dir", help="Path to talks/draft_N/ to resume.")
    p_cont.set_defaults(func=cmd_continue_run)

    p_asm = sub.add_parser("assemble", help="Render slide_spec to .pptx (and optionally .pdf).")
    p_asm.add_argument("draft_dir", help="Path to talks/draft_N/ to assemble.")
    p_asm.add_argument("--format", choices=["pptx", "pdf"], default="pptx",
                       help="Output format. pdf requires LibreOffice on PATH (see SPEC §14.3).")
    p_asm.set_defaults(func=cmd_assemble)

    p_rev = sub.add_parser("revise", help="Targeted post-assembled revision (per-slide / per-substory).")
    p_rev.add_argument("draft_dir", help="Path to talks/draft_N/ to revise.")
    rev_scope = p_rev.add_mutually_exclusive_group(required=True)
    rev_scope.add_argument("--slide", type=int, metavar="N",
                           help="Re-compose slide N only.")
    rev_scope.add_argument("--substory", metavar="ID",
                           help="Re-compose all slides in substory ID.")
    rev_scope.add_argument("--speaker-notes-only", type=int, metavar="N",
                           help="Regenerate speaker notes for slide N only.")
    rev_scope.add_argument("--add-image", type=int, metavar="N",
                           help="Inject AI-generated image into slide N (Channel B, SPEC §8.3).")
    p_rev.add_argument("instruction", help="Free-form revision instruction.")
    p_rev.set_defaults(func=cmd_revise)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
