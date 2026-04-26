#!/usr/bin/env python3
"""merge_compose_fragments.py — assemble per-substory slide_compose
fragments into a single slide_spec.json.

Reads:
  - throughline.md         → throughline_id + punchline + tier
  - substories.md          → ordered (substory_id, punchline) list
  - 03_slides/{S?}_slides.json  → per-substory slide_compose fragments

Produces:
  - slide_spec.json conformant to slide_spec.py's v1 schema, with:
      * stub title slide (id=1)
      * per-substory slides (renumbered, substory_id-tagged)
      * stub acknowledgments slide
      * stub references slide
      * top-level substories[] list with collected slide_ids
      * top-level throughline metadata

Smoke-only behavior:
  - Title / acknowledgments / references slides are STUBS (presenter
    "TBD", contributors ["TBD"], refs_short ["TBD - smoke run"]).
    Production orchestrator will populate these from the project's
    metadata + citation pool.
  - speaker_notes_seed (if present in fragments) is dropped, NOT
    promoted to speaker_notes. Smoke skips speaker_notes.v1; the
    production path runs that prompt before merge and the
    orchestrator injects the result.
  - evidence_anchors (orchestrator metadata, not slide_spec.json
    fields) is dropped on merge.
  - cross_tenant_integration / qa_anticipated slides are NOT spliced
    in v1 smoke (those prompts run in production but not smoke).
  - concept_illustration slides retain the {TBD} placeholders from
    slide_compose and pass through; the orchestrator's downstream
    ai_image_prompt path is also skipped in smoke. Validators may
    flag these — that's expected for the smoke output.

CLI:
    python3 merge_compose_fragments.py \
        --outdir <draft_N>/ \
        --project-id <id> \
        --mode <mode> \
        --tier <tier> \
        --audience peer \
        --throughline-path <draft_N>/00_throughline.md \
        --substory-path <draft_N>/02_substories.md \
        --fragments-dir <draft_N>/03_slides/ \
        --out <draft_N>/slide_spec.json

Exit codes:
  0 — slide_spec.json written
  1 — input file missing / unreadable
  2 — fragment-shape mismatch (e.g., fragment lacks expected fields)
  3 — schema mismatch (fragment_id absent from substories.md)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

# slide_spec.py for SCHEMA_VERSION; if running from source, sys.path
# may not include the tools dir, so we resolve relative to this file.
_TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS_DIR))
import slide_spec  # noqa: E402  (sibling tool)


THROUGHLINE_ID_RE = re.compile(r"<!--\s*chosen:\s*(TL\d+)\s*-->")
THROUGHLINE_PUNCHLINE_RE = re.compile(r"<!--\s*punchline:\s*(.+?)\s*-->")
TIER_RE = re.compile(r"^\*\*Tier:\*\*\s*([A-Z]+)", re.MULTILINE)


def parse_throughline(path: Path) -> dict:
    """Pull throughline_id, punchline, and tier from 00_throughline.md.

    The smoke orchestrator's parse_throughline_candidates.py writes
    HTML-comment metadata at the top of the file; tier comes from the
    candidate body (Tier line).
    """
    text = path.read_text(encoding="utf-8")
    tl_id_m = THROUGHLINE_ID_RE.search(text)
    pl_m = THROUGHLINE_PUNCHLINE_RE.search(text)
    tier_m = TIER_RE.search(text)

    if not tl_id_m:
        raise ValueError(
            f"throughline file missing 'chosen' metadata comment: {path}"
        )

    return {
        "id": tl_id_m.group(1),
        "punchline": pl_m.group(1).strip() if pl_m else "TBD",
        "tier_evidence": tier_m.group(1).strip() if tier_m else "STRONG",
    }


def parse_substories(path: Path) -> list[dict]:
    """Walk substory_design output for the ordered (id, punchline) list.

    Mirrors parse_substories.py's substory_punchlines field but inlined
    here so the merge can be self-contained.
    """
    text = path.read_text(encoding="utf-8")
    header_re = re.compile(
        r"^### (S\d+)\s*[—–-]\s*(.+?)\s*$", re.MULTILINE
    )
    punchline_re = re.compile(
        r"^\*\*Punchline:\*\*\s*(.+?)\s*$", re.MULTILINE
    )

    out: list[dict] = []
    headers = list(header_re.finditer(text))
    for i, m in enumerate(headers):
        sid = m.group(1)
        section_start = m.end()
        section_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        section = text[section_start:section_end]
        pm = punchline_re.search(section)
        punchline = pm.group(1).strip() if pm else f"({sid} punchline TBD)"
        out.append({"id": sid, "punchline": punchline, "slide_ids": []})
    return out


def load_fragments(fragments_dir: Path,
                   substory_ids: list[str]) -> dict[str, dict]:
    """Load each {Sn}_slides.json fragment. Returns {sid: fragment}.

    Raises if a fragment is missing for a declared substory or if a
    fragment has unexpected shape.
    """
    fragments: dict[str, dict] = {}
    for sid in substory_ids:
        path = fragments_dir / f"{sid}_slides.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"fragment missing for substory {sid}: {path}"
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(
                f"fragment {path} is not valid JSON: {e}"
            ) from e
        # Defensive: smoke fragments may not have schema_version or may
        # have placeholder content from the orchestrator's claim_file.
        if "slides" not in data or not isinstance(data["slides"], list):
            raise ValueError(
                f"fragment {path} missing slides[] array"
            )
        fragments[sid] = data
    return fragments


def strip_orchestrator_metadata(slide: dict) -> dict:
    """Remove fields that are orchestrator-internal and not in slide_spec.

    - speaker_notes_seed → dropped (smoke skips speaker_notes)
    - evidence_anchors → dropped (orchestrator metadata)
    - position → replaced by global id at merge
    """
    cleaned = {
        k: v for k, v in slide.items()
        if k not in ("speaker_notes_seed", "evidence_anchors", "position")
    }
    return cleaned


def build_title_slide(slide_id: int, throughline_punchline: str,
                      project_id: str) -> dict:
    """Stub title slide. Production orchestrator populates from project
    metadata; smoke uses placeholders + the throughline punchline as a
    starting title."""
    today = dt.date.today().isoformat()
    return {
        "id": slide_id,
        "layout": "title",
        "content": {
            "title": throughline_punchline if throughline_punchline != "TBD"
                     else f"BERDL project: {project_id}",
            "presenter": "TBD",
            "date": today,
            "subtitle": f"smoke draft for {project_id}",
            "affiliation": "TBD",
        },
    }


def build_acknowledgments_slide(slide_id: int) -> dict:
    return {
        "id": slide_id,
        "layout": "acknowledgments",
        "content": {
            "contributors": ["TBD - populated by production orchestrator"],
            "tenant_attribution": "TBD",
        },
    }


def build_references_slide(slide_id: int) -> dict:
    return {
        "id": slide_id,
        "layout": "references",
        "content": {
            "refs_short": ["TBD - citation_pool not run in smoke"],
            "full_pool_in_speaker_notes": False,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--mode", required=True)
    ap.add_argument("--tier", required=True)
    ap.add_argument("--audience", default="peer")
    ap.add_argument("--throughline-path", required=True)
    ap.add_argument("--substory-path", required=True)
    ap.add_argument("--fragments-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    throughline_path = Path(args.throughline_path)
    substory_path = Path(args.substory_path)
    fragments_dir = Path(args.fragments_dir)
    out_path = Path(args.out)

    if not throughline_path.is_file():
        print(f"Error: throughline file not found: {throughline_path}",
              file=sys.stderr)
        return 1
    if not substory_path.is_file():
        print(f"Error: substory file not found: {substory_path}",
              file=sys.stderr)
        return 1
    if not fragments_dir.is_dir():
        print(f"Error: fragments dir not found: {fragments_dir}",
              file=sys.stderr)
        return 1

    try:
        throughline = parse_throughline(throughline_path)
    except (ValueError, OSError) as e:
        print(f"Error parsing throughline: {e}", file=sys.stderr)
        return 2

    try:
        substories = parse_substories(substory_path)
    except OSError as e:
        print(f"Error reading substory file: {e}", file=sys.stderr)
        return 1

    if not substories:
        print(f"Error: no substories parsed from {substory_path}",
              file=sys.stderr)
        return 2

    substory_ids = [s["id"] for s in substories]
    try:
        fragments = load_fragments(fragments_dir, substory_ids)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading fragments: {e}", file=sys.stderr)
        return 3

    # Build the merged slide list with global IDs.
    slides: list[dict] = []
    next_id = 1

    # 1. Title stub
    slides.append(build_title_slide(next_id, throughline["punchline"],
                                    args.project_id))
    next_id += 1

    # 2. Per-substory slides (in declared order)
    for substory in substories:
        sid = substory["id"]
        fragment = fragments[sid]
        for slide in fragment["slides"]:
            cleaned = strip_orchestrator_metadata(slide)
            cleaned["id"] = next_id
            cleaned["substory_id"] = sid
            substory["slide_ids"].append(next_id)
            slides.append(cleaned)
            next_id += 1

    # 3. Acknowledgments stub
    slides.append(build_acknowledgments_slide(next_id))
    next_id += 1

    # 4. References stub
    slides.append(build_references_slide(next_id))

    # Build the top-level spec object
    spec = {
        "schema_version": slide_spec.SCHEMA_VERSION,
        "project_id": args.project_id,
        "mode": args.mode,
        "audience": args.audience,
        "tier": args.tier,
        "throughline": throughline,
        "substories": substories,
        "slides": slides,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"  -> merged {len(slides)} slides across "
          f"{len(substories)} substories", file=sys.stderr)
    print(f"     wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
