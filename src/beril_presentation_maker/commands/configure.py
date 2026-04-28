"""`beril-presentation-maker configure` — comprehensive environment audit.

Verify that the runtime environment can support the full presentation-maker
pipeline. Surfaces problems at install/configure time rather than
mid-pipeline, where each $0.50–$2 retry hurts.

Checks (in order):

  Hard requirements (return 3 if missing):
  - `claude` CLI on PATH
  - The Python interpreter the orchestrator will resolve via
    presentation_maker.sh's discover_python_bin (typically the pipx
    venv's python). Has the right runtime deps (`python-pptx`,
    `nbformat`, `Pillow`).

  Soft requirements (warn only):
  - `beril-adversarial-cli` on PATH (review-rewrite loop falls back to
    inline reviewer; v0.3.0 will gate the loop on this).
  - `requests` Python module (optional ai_image_prompt CBORG client).
  - LibreOffice (`soffice`) on PATH — required only for `--format pdf`.
  - `mmdc` (mermaid-cli) — required only for the v0.3+ mermaid-diagram
    code path; not needed for v0.2.
  - POSIX core utilities (basename, cat, cp, cut, date, dirname, echo,
    grep, head, hostname, ls, mkdir, readlink, rm, sed, sort, touch).
  - bash version (>= 3.2)

  Informational:
  - WebSearch availability — not checked directly; verified at run time
    by citation_pool.v1.

Per the presentation-maker DECISIONS doc, the assembly path uses
`python-pptx` so a pipx install is fully self-contained. PDF output
adds an optional LibreOffice dependency.

Exit codes:
  0 — all hard requirements met
  3 — at least one hard requirement missing
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from beril_presentation_maker import __version__, discovery


_POSIX_UTILITIES = (
    "basename", "cat", "cp", "cut", "date", "dirname", "echo",
    "grep", "head", "hostname", "ls", "mkdir", "readlink", "rm",
    "sed", "sort", "touch",
)


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "configure",
        help="Verify the claude CLI is installed; report optional dep status.",
        description=(
            "Comprehensive environment audit. Verifies hard requirements "
            "(claude CLI, Python interpreter with python-pptx + nbformat + "
            "Pillow) and reports soft-requirement status (beril-adversarial "
            "fallback, LibreOffice for PDF export, mermaid-cli for v0.3+ "
            "diagrams, POSIX utilities, bash version)."
        ),
    )
    p.add_argument(
        "--beril-root",
        help="Explicit BERIL_ROOT (used only for the status banner).",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-check output; print only summary + return exit code.",
    )
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace) -> int:
    quiet = getattr(args, "quiet", False)
    hard_failures: list[str] = []
    soft_warnings: list[str] = []

    def _info(msg: str) -> None:
        if not quiet:
            print(msg)

    def _err(msg: str) -> None:
        if not quiet:
            print(msg, file=sys.stderr)

    try:
        beril_root = discovery.find_beril_root(
            explicit=getattr(args, "beril_root", None)
        )
    except discovery.BerilRootNotFound:
        beril_root = None

    _info(f"beril-presentation-maker-skill v{__version__}")
    if beril_root is not None:
        _info(f"  BERIL_ROOT: {beril_root}")
    _info("")
    _info("=== Hard requirements ===")

    # ---- 1. claude CLI ----
    claude_path = shutil.which("claude")
    if claude_path is None:
        _err("  [MISSING] claude CLI not found on PATH.")
        _err("            Install Claude Code (https://docs.claude.com) and retry.")
        hard_failures.append("claude CLI")
    else:
        version_str = _safe_version(["claude", "--version"], default="(version unknown)")
        _info(f"  [OK]      claude              — {claude_path}  {version_str}")

    # ---- 2. Python interpreter the orchestrator resolves ----
    py_path = _resolve_orchestrator_python()
    if not py_path or not py_path.is_file():
        _err("  [MISSING] Cannot resolve orchestrator's Python interpreter.")
        _err("            Expected via the pipx wrapper script's shebang.")
        _err("            Reinstall: pipx install --force beril-presentation-maker-skill")
        hard_failures.append("orchestrator Python interpreter")
        py_path = None
    else:
        py_version = _safe_version([str(py_path), "--version"], default="(unknown)")
        _info(f"  [OK]      orchestrator-python — {py_path}  {py_version}")

    # ---- 3. python-pptx (assemble step; v0.2 dependency) ----
    if py_path is not None:
        pptx_version = _check_module_in(py_path, "pptx")
        if pptx_version:
            _info(f"  [OK]      python-pptx         — {pptx_version}  (used by `assemble` to render .pptx)")
        else:
            _err("  [MISSING] python-pptx not importable by orchestrator-python.")
            _err("            `beril-presentation-maker assemble` will fail.")
            _err("            Reinstall: pipx install --force beril-presentation-maker-skill")
            hard_failures.append("python-pptx")

    # ---- 4. nbformat (used by curate_figures.py savefig walk) ----
    if py_path is not None:
        nb_version = _check_module_in(py_path, "nbformat")
        if nb_version:
            _info(f"  [OK]      nbformat            — {nb_version}  (used by curate_figures.py)")
        else:
            _err("  [MISSING] nbformat not importable by orchestrator-python.")
            _err("            curate_figures notebook-savefig walk will skip; figure")
            _err("            captions degrade to filename-derived only.")
            hard_failures.append("nbformat")

    # ---- 5. Pillow (figure validators) ----
    if py_path is not None:
        pil_version = _check_module_in(py_path, "PIL")
        if pil_version:
            _info(f"  [OK]      Pillow              — {pil_version}  (figure resolution checks)")
        else:
            _err("  [MISSING] Pillow not importable by orchestrator-python.")
            _err("            P6 figure-resolution validator will skip.")
            hard_failures.append("Pillow")

    _info("")
    _info("=== Soft requirements ===")

    # ---- 6. beril-adversarial CLI (soft; v0.3+ review-rewrite loop) ----
    adv_path = shutil.which("beril-adversarial-cli")
    if adv_path:
        _info(f"  [OK]      beril-adversarial   — {adv_path}")
    else:
        _info(
            "  [absent]  beril-adversarial   — not on PATH; v0.3+ review-rewrite "
            "loop will fall back to inline reviewer."
        )
        _info(
            "            To install: pipx install --force "
            "git+ssh://git@github.com/ArkinLaboratory/beril-adversarial-skill.git"
        )

    # ---- 7. requests (optional CBORG image-gen client) ----
    if py_path is not None:
        req_version = _check_module_in(py_path, "requests")
        if req_version:
            _info(f"  [OK]      requests            — {req_version}  (optional ai_image_prompt client)")
        else:
            _info("  [absent]  requests            — ai_image_prompt CBORG client unavailable")
            soft_warnings.append("requests (image-gen optional)")

    # ---- 8. LibreOffice (--format pdf only) ----
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        _info(f"  [OK]      LibreOffice         — {soffice}  (used for --format pdf)")
    else:
        _info(
            "  [absent]  LibreOffice         — needed only for "
            "`assemble --format pdf`. .pptx export works without it."
        )

    # ---- 9. mermaid-cli (v0.3+ diagram path) ----
    mmdc = shutil.which("mmdc")
    if mmdc:
        _info(f"  [OK]      mermaid-cli (mmdc)  — {mmdc}  (v0.3+ diagrams)")
    else:
        _info("  [absent]  mermaid-cli (mmdc)  — not used in v0.2; required for v0.3+ mermaid diagrams")

    # ---- 10. bash version ----
    bash_v = _safe_version(["bash", "--version"], default="")
    if bash_v:
        m = re.search(r"version\s+(\d+)\.(\d+)", bash_v)
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            ver_str = f"{major}.{minor}"
            if (major, minor) >= (3, 2):
                _info(f"  [OK]      bash                — {ver_str} (>= 3.2 required)")
            else:
                _err(f"  [LOW]     bash                — {ver_str} (need >= 3.2)")
                soft_warnings.append(f"bash {ver_str} below 3.2")
        else:
            _info(f"  [OK]      bash                — version unparseable but present")
    else:
        _err("  [MISSING] bash not on PATH (very unusual).")
        soft_warnings.append("bash")

    # ---- 11. POSIX core utilities ----
    missing_utils = [u for u in _POSIX_UTILITIES if shutil.which(u) is None]
    if not missing_utils:
        _info(f"  [OK]      POSIX utilities     — all {len(_POSIX_UTILITIES)} present")
    else:
        _err(f"  [MISSING] POSIX utilities     — {len(missing_utils)} missing: {', '.join(missing_utils)}")
        _err("            Orchestrator may fail at random points. Container or")
        _err("            sandbox is unusually stripped down.")
        soft_warnings.append(f"POSIX utilities missing: {missing_utils}")

    _info("")
    _info("=== Informational ===")
    _info(
        "  [info]    WebSearch           — used by citation_pool.v1. "
        "Not checked here; verified at run time."
    )

    _info("")
    _info("=== Summary ===")
    if hard_failures:
        _err(f"  ❌ {len(hard_failures)} hard failure(s): {', '.join(hard_failures)}")
        _err("     Pipeline will not run reliably. Fix these before invoking /beril-presentation-maker.")
        return 3
    if soft_warnings:
        _info(f"  ⚠ {len(soft_warnings)} soft warning(s) (pipeline will run, may degrade): {', '.join(soft_warnings)}")
    else:
        _info("  ✓ All hard requirements met.")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_version(cmd: list[str], default: str = "(unknown)") -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5, check=False,
        )
        out = (result.stdout or result.stderr or "").strip()
        return out.splitlines()[0] if out else default
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return default


def _resolve_orchestrator_python() -> Path | None:
    """Mirror presentation_maker.sh's `discover_python_bin` logic.

    Priority:
      1. $BERIL_PRESENTATION_MAKER_PYTHON if set + executable
      2. Shebang of `which beril-presentation-maker` (the pipx wrapper)
      3. `python3` on PATH (warned-against fallback)
    """
    env_python = os.environ.get("BERIL_PRESENTATION_MAKER_PYTHON")
    if env_python:
        p = Path(env_python)
        if p.is_file() and os.access(p, os.X_OK):
            return p

    cli_path = shutil.which("beril-presentation-maker")
    if cli_path:
        try:
            with open(cli_path, encoding="utf-8") as f:
                first_line = f.readline().strip()
            if first_line.startswith("#!"):
                rest = first_line[2:].lstrip()
                first_word = rest.split()[0] if rest.split() else ""
                if first_word == "/usr/bin/env":
                    parts = rest.split()
                    if len(parts) >= 2:
                        resolved = shutil.which(parts[1])
                        if resolved:
                            return Path(resolved)
                else:
                    candidate = Path(first_word)
                    if candidate.is_file():
                        return candidate
        except (OSError, UnicodeDecodeError):
            pass

    sys_p = shutil.which("python3")
    if sys_p:
        return Path(sys_p)
    return None


def _check_module_in(python_path: Path, module: str) -> str | None:
    """Run the resolved Python interpreter to check if a module imports.
    Returns __version__ if importable, None otherwise.
    """
    code = (
        f"import {module}; print(getattr({module}, '__version__', '(version unknown)'))"
    )
    try:
        result = subprocess.run(
            [str(python_path), "-c", code],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out if out else "(version unknown)"
