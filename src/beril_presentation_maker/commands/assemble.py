"""`beril-presentation-maker assemble <draft_dir>` — render slide_spec to .pptx.

Thin Python wrapper around `assemble_pptx.assemble()`. Resolves the
slide_spec.json path in this order (v1.1.1+):

  1. <draft_dir>/working/slide_spec.json   (CRAFT-CONTRACT §3.1 4-zone —
                                            the path the pipeline writes)
  2. <draft_dir>/slide_spec.json           (flat, backward-compat fallback)

Output goes to <draft_dir>/deliverable/draft.pptx when the 4-zone layout
is present (deliverable/ directory exists), else to <draft_dir>/draft.pptx
(legacy flat layout). --out always overrides.

For PDF output (`--format pdf`), delegates to LibreOffice's
`soffice --headless --convert-to pdf`. If LibreOffice is absent,
emits .pptx only and prints a clear message.

This is a direct Python invocation (not a shell wrapper) because
assemble_pptx is pure Python; no need to round-trip through bash.

Pre-v1.1.1 only the flat path was tried, forcing operators to copy the
spec out of working/ before calling assemble — surfaced live on the
caulobacter hub run 2026-06-07.
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
            "Resolve the slide_spec.json under <draft_dir> (preferring "
            "working/slide_spec.json per the 4-zone layout; falling back "
            "to the flat <draft_dir>/slide_spec.json for backward-compat), "
            "validate, and render to deliverable/draft.pptx (or "
            "<draft_dir>/draft.pptx in the flat layout). With --format "
            "pdf, also produces draft.pdf via LibreOffice."
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


def _resolve_spec_path(draft_dir: Path) -> Path | None:
    """Resolve slide_spec.json under draft_dir.

    v1.1.1: prefer working/slide_spec.json (4-zone layout — what the
    pipeline writes) over the flat path. Returns None if neither exists.
    """
    working_path = draft_dir / "working" / "slide_spec.json"
    if working_path.is_file():
        return working_path
    flat_path = draft_dir / "slide_spec.json"
    if flat_path.is_file():
        return flat_path
    return None


def run(args: argparse.Namespace) -> int:
    draft_dir = Path(args.draft_dir).expanduser().resolve()
    if not draft_dir.is_dir():
        print(f"error: draft_dir does not exist: {draft_dir}", file=sys.stderr)
        return 1

    spec_path = _resolve_spec_path(draft_dir)
    if spec_path is None:
        print(
            f"error: slide_spec.json not found at "
            f"{draft_dir/'working'/'slide_spec.json'} or {draft_dir/'slide_spec.json'}. "
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

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
    else:
        # 4-zone layout: write to deliverable/draft.pptx when the
        # deliverable/ directory exists; else fall back to the flat
        # <draft_dir>/draft.pptx legacy location.
        deliverable_dir = draft_dir / "deliverable"
        if deliverable_dir.is_dir():
            out_path = deliverable_dir / "draft.pptx"
        else:
            out_path = draft_dir / "draft.pptx"

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
