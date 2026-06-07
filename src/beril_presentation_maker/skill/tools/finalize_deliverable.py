#!/usr/bin/env python3
"""finalize_deliverable.py — Cycle 1 remediation half (separated from
detection per the brief).

Reads the most-recent `audit/deliverable_validation.json` produced by
`validate_deliverable.py check`, applies the deterministic
auto-remediations the findings prescribe, re-runs validate, and writes
the final readiness verdict. Targeted-remediable + advisory findings
are surfaced (not auto-applied) — the operator runs those.

Never re-runs the pipeline. Never invokes an LLM. The most expensive
auto-remediation in scope is a single `assemble` re-run (~seconds, no
network).

CONTRACT WITH validate_deliverable.py:
  - validate emits Findings with `remediation.kind ∈ {auto, targeted,
    advisory}`.
  - For each `kind=auto` finding, finalize_deliverable dispatches on
    `remediation.action` to a handler. The handlers below.
  - After all auto-remediations attempt to apply, finalize calls
    validate_deliverable.validate() again. The second pass's findings
    are the canonical "what's left" and what the operator sees.
  - Exit code = readiness_exit_code(second-pass findings). The
    deliverable is ALWAYS produced; never deleted, never recomputed
    upstream of assemble. Sunk-cost-safe.

The auto handlers below are minimal and safe-by-construction:

  reassemble:                 re-run assemble_pptx.assemble() against the
                              current working/slide_spec.json.

  populate_title_from_beril:  read <project_dir>/beril.yaml, splice
                              authors[0] into the title slide's presenter
                              + affiliation (and acknowledgments
                              contributors), write spec back, request
                              a reassemble pass.

  strip_dirname_token:        strip the project-directory name token
                              from the title slide's title field, write
                              spec back, request a reassemble pass.

Reassemble is requested AT MOST once per finalize invocation even if
multiple findings ask for it (idempotent: the result is the same).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS_DIR))


# ---------------------------------------------------------------------------
# Spec read/write helpers
# ---------------------------------------------------------------------------


def _spec_path(draft_dir: Path) -> Path:
    """Mirror validate_deliverable / assemble's path-resolution preference."""
    p = draft_dir / "working" / "slide_spec.json"
    if p.is_file():
        return p
    return draft_dir / "slide_spec.json"


def _load_spec(draft_dir: Path) -> dict | None:
    path = _spec_path(draft_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_spec(draft_dir: Path, spec: dict) -> Path:
    path = _spec_path(draft_dir)
    # Match merge_compose_fragments' write shape: indent=2, ensure_ascii
    # False, trailing newline.
    path.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Auto-remediations
# ---------------------------------------------------------------------------


def _populate_from_beril_yaml(draft_dir: Path) -> tuple[bool, str]:
    """Auto-action populate_title_from_beril.

    Reads <project_dir>/beril.yaml; pulls authors[0].name +
    authors[0].affiliation; writes them into the title slide's
    presenter + affiliation and into acknowledgments contributors.
    Returns (mutated, message). False + reason if nothing changed (file
    missing, no authors block, etc.).
    """
    spec = _load_spec(draft_dir)
    if spec is None:
        return False, "slide_spec.json missing or unreadable"

    # Locate beril.yaml the same way the validator does.
    import validate_deliverable as vd  # noqa: E402
    parsed = vd._load_beril_yaml(draft_dir)
    if parsed is None:
        return False, "beril.yaml missing, unparseable, or has no authors"
    authors = parsed.get("authors") or []
    if not isinstance(authors, list) or not authors:
        return False, "beril.yaml has no authors[]"
    primary = authors[0]
    if not isinstance(primary, dict):
        return False, "beril.yaml authors[0] not a mapping"
    name = primary.get("name") or ""
    affiliation = primary.get("affiliation") or ""
    if not name:
        return False, "beril.yaml authors[0] missing name"

    mutated = False
    for slide in spec.get("slides", []):
        layout = slide.get("layout")
        content = slide.setdefault("content", {})
        if layout == "title":
            if vd._is_tbd(content.get("presenter")):
                content["presenter"] = name
                mutated = True
            if affiliation and vd._is_tbd(content.get("affiliation")):
                content["affiliation"] = affiliation
                mutated = True
        elif layout == "acknowledgments":
            contributors = content.get("contributors") or []
            if not contributors or all(vd._is_tbd(c) for c in contributors):
                # Replace with a single entry built from beril.yaml's
                # author list — names + (optional) affiliations.
                new_contribs: list[str] = []
                for a in authors:
                    if not isinstance(a, dict):
                        continue
                    nm = a.get("name")
                    if not nm:
                        continue
                    aff = a.get("affiliation")
                    new_contribs.append(
                        f"{nm} · {aff}" if aff else nm
                    )
                if new_contribs:
                    content["contributors"] = new_contribs
                    mutated = True

    if not mutated:
        return False, "no TBD title/presenter/contributors fields to populate"
    _write_spec(draft_dir, spec)
    return True, (
        f"populated title presenter='{name}' from beril.yaml"
        + (f", affiliation='{affiliation}'" if affiliation else "")
    )


def _strip_dirname_token(draft_dir: Path) -> tuple[bool, str]:
    """Auto-action strip_dirname_token.

    Removes the project-directory name (and its distinctive ≥5-char
    word-tokens) from the title slide's title field. Conservative: we
    delete the token + collapse surrounding whitespace; we DO NOT
    rewrite — if the result is empty/degenerate, leave the field as-is
    and the populate_title path or operator-targeted command takes
    over.
    """
    spec = _load_spec(draft_dir)
    if spec is None:
        return False, "slide_spec.json missing or unreadable"

    import validate_deliverable as vd  # noqa: E402
    dirname_token = vd._project_dir_token(draft_dir)
    if not dirname_token:
        return False, "project_dir not detectable; no token to strip"

    title_slide = next(
        (s for s in spec.get("slides", []) if s.get("layout") == "title"),
        None,
    )
    if title_slide is None:
        return False, "no title slide to strip"
    content = title_slide.setdefault("content", {})
    title = content.get("title") or ""
    if not isinstance(title, str) or not title:
        return False, "title is empty or non-string"
    if not vd._contains_dirname_token(title, dirname_token):
        return False, "title does not contain dirname token"

    # Build the strip pattern: the full dirname (lower) + distinctive
    # ≥5-char tokens. Match word-boundary, case-insensitive.
    norm_token = dirname_token.lower()
    tokens = re.split(r"[_\-.\s]+", norm_token)
    distinctive = [t for t in tokens if len(t) >= 5]
    patterns = [re.escape(norm_token)] + [re.escape(t) for t in distinctive]
    pattern = "|".join(patterns)
    new_title = re.sub(
        rf"\b({pattern})\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    # Collapse double-spaces + trim leading/trailing punctuation.
    new_title = re.sub(r"\s+", " ", new_title).strip(" ,.;:-—–")
    if not new_title or new_title == title:
        return False, (
            "stripping the dirname token left an empty/unchanged title; "
            "leaving as-is for operator review"
        )
    content["title"] = new_title
    _write_spec(draft_dir, spec)
    return True, (
        f"stripped dirname token from title: {title!r} -> {new_title!r}"
    )


def _reassemble(draft_dir: Path) -> tuple[bool, str]:
    """Auto-action reassemble. Re-run assemble_pptx.assemble() against
    the current spec; write to deliverable/draft.pptx (or
    <draft_dir>/draft.pptx if no deliverable/)."""
    import importlib.util
    asm_py = _TOOLS_DIR / "assemble_pptx.py"
    spec = importlib.util.spec_from_file_location("_fd_assemble_pptx", asm_py)
    if spec is None or spec.loader is None:
        return False, "could not load assemble_pptx for reassemble"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_fd_assemble_pptx"] = mod
    spec.loader.exec_module(mod)

    spec_path = _spec_path(draft_dir)
    if not spec_path.is_file():
        return False, "slide_spec.json missing; cannot reassemble"

    deliverable = draft_dir / "deliverable"
    out_path = (
        deliverable / "draft.pptx" if deliverable.is_dir()
        else draft_dir / "draft.pptx"
    )

    try:
        mod.assemble(str(spec_path), str(out_path))
    except Exception as exc:
        return False, f"assemble re-run failed: {exc!r}"
    return True, f"reassembled deck at {out_path}"


_AUTO_HANDLERS = {
    "populate_title_from_beril": _populate_from_beril_yaml,
    "strip_dirname_token": _strip_dirname_token,
    "reassemble": _reassemble,
}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _load_findings(draft_dir: Path) -> dict | None:
    """Read audit/deliverable_validation.json. None on missing/malformed."""
    path = draft_dir / "audit" / "deliverable_validation.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def finalize(draft_dir: Path) -> dict:
    """Apply auto-remediations from the first-pass findings; re-run
    validate; return a small dict of {actions_applied, second_pass_summary,
    targeted_commands, advisory_notes}. Pure orchestration; the heavy
    work is in _AUTO_HANDLERS + validate_deliverable.validate."""
    payload = _load_findings(draft_dir)
    if payload is None:
        return {
            "error": (
                "no audit/deliverable_validation.json found; "
                "run `validate_deliverable check <draft_dir>` first."
            ),
        }
    first_pass = payload.get("findings") or []

    # 1. Gather and de-dup the auto-actions requested. Reassemble is
    #    requested implicitly whenever a content-mutating action ran;
    #    explicit AUTO_REASSEMBLE findings (e.g. G5 aspect_skew) also
    #    add it to the queue.
    requested_actions: list[str] = []
    for f in first_pass:
        rem = f.get("remediation") or {}
        if rem.get("kind") != "auto":
            continue
        action = rem.get("action")
        if action in _AUTO_HANDLERS and action not in requested_actions:
            requested_actions.append(action)

    # Spec-mutating actions must run BEFORE reassemble so the rerun
    # picks up the new spec.
    spec_mutating = [
        a for a in requested_actions
        if a in ("populate_title_from_beril", "strip_dirname_token")
    ]
    will_reassemble = "reassemble" in requested_actions or bool(spec_mutating)
    ordered = list(spec_mutating)
    if will_reassemble:
        ordered.append("reassemble")

    actions_applied: list[dict] = []
    for action in ordered:
        handler = _AUTO_HANDLERS[action]
        ok, msg = handler(draft_dir)
        actions_applied.append({
            "action": action,
            "applied": bool(ok),
            "message": msg,
        })

    # 2. Re-validate. If nothing was applied, this still re-runs (cheap)
    #    so the operator sees a fresh-as-of-now picture.
    import validate_deliverable as vd  # noqa: E402
    second_pass = vd.validate(draft_dir)
    vd.write_findings(draft_dir, second_pass)
    second_summary = vd._summarize(second_pass)

    # 3. Pull targeted commands + advisory notes from the SECOND pass —
    #    those are what the operator still needs to act on.
    targeted_commands: list[dict] = []
    advisory_notes: list[dict] = []
    for f in second_pass:
        rem = f.remediation
        if rem.kind == "targeted":
            targeted_commands.append({
                "id": f.id,
                "gate": f.gate,
                "severity": f.severity,
                "command": rem.command,
                "note": rem.note,
            })
        elif rem.kind == "advisory":
            advisory_notes.append({
                "id": f.id,
                "gate": f.gate,
                "severity": f.severity,
                "message": f.message,
                "note": rem.note,
            })

    return {
        "actions_applied": actions_applied,
        "second_pass_summary": second_summary,
        "second_pass_readiness_rc": vd.readiness_exit_code(second_pass),
        "targeted_commands": targeted_commands,
        "advisory_notes": advisory_notes,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_finalize(args: argparse.Namespace) -> int:
    draft_dir = Path(args.draft_dir).resolve()
    if not draft_dir.is_dir():
        print(
            f"finalize_deliverable: draft_dir not found: {draft_dir}",
            file=sys.stderr,
        )
        return 2

    result = finalize(draft_dir)
    if "error" in result:
        print(f"finalize_deliverable: {result['error']}", file=sys.stderr)
        return 2

    actions = result["actions_applied"]
    if actions:
        print(
            f"finalize_deliverable: auto-applied {len(actions)} "
            f"remediation action(s):",
            file=sys.stderr,
        )
        for a in actions:
            tag = "✓" if a["applied"] else "·"
            print(f"  {tag} {a['action']}: {a['message']}", file=sys.stderr)
    else:
        print(
            "finalize_deliverable: no auto-remediations requested.",
            file=sys.stderr,
        )

    s = result["second_pass_summary"]
    print(
        f"finalize_deliverable: post-remediation — total={s['total']}, "
        f"P0={s['by_severity'].get('P0', 0)}, "
        f"P1={s['by_severity'].get('P1', 0)}, "
        f"advisory={s['by_severity'].get('advisory', 0)}",
        file=sys.stderr,
    )

    if result["targeted_commands"]:
        print(
            f"finalize_deliverable: {len(result['targeted_commands'])} "
            f"targeted-remediation command(s) — these need operator action:",
            file=sys.stderr,
        )
        for c in result["targeted_commands"]:
            print(f"  [{c['severity']}] {c['gate']}: {c['note']}", file=sys.stderr)
            if c["command"]:
                print(f"    $ {c['command']}", file=sys.stderr)

    if result["advisory_notes"]:
        print(
            f"finalize_deliverable: {len(result['advisory_notes'])} "
            f"advisory finding(s):",
            file=sys.stderr,
        )
        for n in result["advisory_notes"]:
            print(f"  • {n['gate']}: {n['message']}", file=sys.stderr)

    return result["second_pass_readiness_rc"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="finalize_deliverable",
        description=(
            "Cycle 1 remediation half. Reads "
            "audit/deliverable_validation.json, applies "
            "auto-remediations, re-runs validation, surfaces "
            "targeted commands + advisories. Never re-runs the "
            "pipeline. Exit code = post-remediation readiness."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_fin = sub.add_parser(
        "finalize",
        help="Apply auto-remediations + re-validate.",
    )
    p_fin.add_argument("draft_dir")
    p_fin.set_defaults(func=_cmd_finalize)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
