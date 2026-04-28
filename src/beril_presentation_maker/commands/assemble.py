"""`beril-presentation-maker assemble <draft_dir>` — render slide_spec to .pptx.

Thin Python wrapper around `assemble_pptx.assemble()`. Looks for
`<draft_dir>/slide_spec.json`, validates it (slide_spec.py preflight),
and writes `<draft_dir>/draft.pptx`.

For PDF output (`--format pdf`), delegates to LibreOffice's
`soffice --headless --convert-to pdf`. If LibreOffice is absent,
emits .pptx only and prints a clear message.

This is a direct Python invocation (not a shell wrapper) because
assemble_pptx is pure Python; no need to round-trip through bash.
"""

from __future__ import annotations

import argparse
import sys
from importlib import resources
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

from beril_presentation_maker import __version__


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "assemble",
        help="Render slide_spec.json to .pptx (and optionally .pdf).",
        description=(
            "Read <draft_dir>/slide_spec.json, validate, and render to "
            "<draft_dir>/draft.pptx. With --format pdf, also produces "
            "draft.pdf via LibreOffice."
        ),
    )
    p.add_argument(
        "draft_dir",
        help="Path to talks/draft_N/ to assemble.",
    )
    p.add_argument(
        "--format",
        choices=["pptx", "pdf"],
        default="pptx",
        help="Output format (default: pptx). pdf requires LibreOffice on PATH.",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Override output filename (default: <draft_dir>/draft.pptx).",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Treat any assembler warning as a hard failure.",
    )
    p.set_defaults(func=run)
    return p


def _load_assemble_module() -> Any:
    """Load the shipped assemble_pptx module from the package data.

    Uses importlib.util to load it directly from the file path so the
    module's _DEFAULT_MASTER constant resolves correctly to the shipped
    template alongside it.
    """
    try:
        ref = resources.files("beril_presentation_maker").joinpath(
            "skill", "tools", "assemble_pptx.py"
        )
        with resources.as_file(ref) as p:
            asm_path = Path(p)
    except (ModuleNotFoundError, FileNotFoundError) as e:
        raise FileNotFoundError(
            "assemble_pptx.py not found in package data. "
            "Reinstall beril-presentation-maker-skill."
        ) from e

    # Register in sys.modules BEFORE exec_module per the
    # feedback_importlib_dataclass_gotcha memory: any module with
    # @dataclass loaded via spec_from_file_location MUST be registered
    # in sys.modules before exec_module, or NoneType crashes ensue.
    spec = spec_from_file_location("_pm_assemble_pptx", asm_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load module spec for {asm_path}")
    module = module_from_spec(spec)
    sys.modules["_pm_assemble_pptx"] = module
    spec.loader.exec_module(module)
    return module


def run(args: argparse.Namespace) -> int:
    draft_dir = Path(args.draft_dir).expanduser().resolve()
    if not draft_dir.is_dir():
        print(f"error: draft_dir does not exist: {draft_dir}", file=sys.stderr)
        return 1

    spec_path = draft_dir / "slide_spec.json"
    if not spec_path.is_file():
        print(
            f"error: slide_spec.json not found at {spec_path}. "
            f"Run `beril-presentation-maker draft <project>` first or "
            f"`beril-presentation-maker continue <draft_dir> --resume-from merge`.",
            file=sys.stderr,
        )
        return 1

    try:
        asm = _load_assemble_module()
    except (FileNotFoundError, ImportError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    out_path = (
        Path(args.out).expanduser().resolve()
        if args.out
        else draft_dir / "draft.pptx"
    )

    print(f"▸ Assembling {spec_path} → {out_path}", file=sys.stderr)
    try:
        result = asm.assemble(spec_path, out_path, strict=args.strict)
    except Exception as e:
        # AssemblyError or any other exception from the assembler.
        print(f"error: assembly failed: {e}", file=sys.stderr)
        return 2

    if result.warnings:
        print(
            f"⚠ {len(result.warnings)} warning(s) during assembly:",
            file=sys.stderr,
        )
        for w in result.warnings:
            print(f"    {w}", file=sys.stderr)
        if args.strict:
            print(
                "error: --strict was set; treating warnings as failure.",
                file=sys.stderr,
            )
            return 2

    print(f"✓ Assembled: {result.out_path}")

    # Optional PDF rendering via LibreOffice
    if args.format == "pdf":
        print(f"▸ Rendering PDF via LibreOffice", file=sys.stderr)
        pdf_path = asm.render_pdf(Path(result.out_path))
        if pdf_path is None:
            print(
                "⚠ PDF render skipped: 'soffice' / 'libreoffice' not on PATH. "
                ".pptx-only output is still valid.",
                file=sys.stderr,
            )
        else:
            print(f"✓ Rendered: {pdf_path}")
    return 0
