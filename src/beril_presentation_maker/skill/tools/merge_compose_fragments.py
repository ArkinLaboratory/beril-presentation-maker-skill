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
    """Build the title slide.

    2026-04-26 visual review found the prior version used the full
    throughline punchline (often 200-300 chars) as the title, causing
    catastrophic overrun on the title placeholder (5x oversize) — text
    spilled over the KBase logo. The fix:

      - Title  = project_id rendered title-case (e.g. `functional_dark_matter`
                 → `Functional Dark Matter`). Short, fits the placeholder
                 cleanly.
      - Subtitle = throughline punchline (the full claim). Larger
                 placeholder + autofit on the master handles longer text.

    Production orchestrator will eventually replace this with a project-
    metadata-driven title (RESEARCH_PLAN-derived short title), but the
    project_id title-case is the reasonable v0.1 stub.
    """
    today = dt.date.today().isoformat()

    # Render project_id as a human-readable title:
    # `functional_dark_matter` → `Functional Dark Matter`
    # `cf-formulation-design`  → `Cf Formulation Design`
    title_text = project_id.replace("_", " ").replace("-", " ").title().strip()
    if not title_text:
        title_text = f"BERDL project: {project_id}"

    # Subtitle carries a TRUNCATED version of the throughline punchline.
    # 2026-04-26 followup: full punchline (200-300 chars) overflowed the
    # subtitle placeholder even with autofit (which fontScale=80% can't
    # rescue at 30%-required shrink). Truncate at the last word boundary
    # ≤120 chars + ellipsis — the full claim lives in 00_throughline.md
    # for the speaker; the subtitle is just an audience teaser.
    SUBTITLE_CAP = 120
    if not throughline_punchline or throughline_punchline == "TBD":
        subtitle = ""
    elif len(throughline_punchline) <= SUBTITLE_CAP:
        subtitle = throughline_punchline
    else:
        # Truncate at last word boundary ≤ cap-3 (room for "...")
        cut = throughline_punchline.rfind(" ", 0, SUBTITLE_CAP - 3)
        if cut < 0:
            cut = SUBTITLE_CAP - 3
        subtitle = throughline_punchline[:cut].rstrip(" ,;") + "…"

    content = {
        "title": title_text,
        "presenter": "TBD",
        "date": today,
        "affiliation": "TBD",
    }
    if subtitle:
        content["subtitle"] = subtitle

    return {
        "id": slide_id,
        "layout": "title",
        "content": content,
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


def load_speaker_notes_for_substory(
    notes_dir: Path | None, substory_id: str
) -> dict[int, str]:
    """Load parsed speaker notes for a substory.

    Reads `{notes_dir}/{substory_id}_notes.json` (the parsed output
    from parse_speaker_notes.py). Returns a dict mapping per-substory
    position (0-indexed within the substory's slides) → notes text.

    Returns {} if the file is absent (speaker_notes stage skipped) or
    malformed (warns and proceeds without notes).
    """
    if notes_dir is None:
        return {}
    notes_path = notes_dir / f"{substory_id}_notes.json"
    if not notes_path.is_file():
        return {}
    try:
        data = json.loads(notes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: cannot parse speaker notes at {notes_path}: {e}",
              file=sys.stderr)
        return {}
    raw = data.get("notes_by_position", {}) or {}
    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            out[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    return out


def load_intro_fragment(path: Path | None) -> list[dict]:
    """Load the intro fragment (intro.json) if present and non-empty.

    Returns the list of intro slide objects (may be empty for
    lightning-5 / posters). Returns [] if the path is None or the
    file doesn't exist (intro stage was skipped).

    Defensive against malformed JSON: logs a warning and returns []
    rather than crashing the merge — intro is non-load-bearing in
    smoke mode, so a parse error shouldn't break the whole pipeline.
    """
    if path is None or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: cannot parse intro fragment at {path}: {e}",
              file=sys.stderr)
        print("  proceeding without intro slides", file=sys.stderr)
        return []
    slides = data.get("slides", [])
    if not isinstance(slides, list):
        print(f"Warning: intro fragment {path} has non-list slides; "
              f"proceeding without intro", file=sys.stderr)
        return []
    return slides


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
    ap.add_argument("--intro-fragment-path", default=None,
                    help="Optional path to intro.json (intro stage output). "
                         "If absent or empty, no intro slides are spliced.")
    ap.add_argument("--speaker-notes-dir", default=None,
                    help="Optional directory containing parsed speaker "
                         "notes JSON files ({substory_id}_notes.json). "
                         "If present, speaker_notes are injected into "
                         "per-substory slides at merge time. Absent → "
                         "slides ship without speaker notes.")
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

    intro_path = (Path(args.intro_fragment_path)
                  if args.intro_fragment_path else None)
    intro_slides = load_intro_fragment(intro_path)

    # Build the merged slide list with global IDs.
    slides: list[dict] = []
    next_id = 1

    # 1. Title stub
    slides.append(build_title_slide(next_id, throughline["punchline"],
                                    args.project_id))
    next_id += 1

    # 2. Intro slides (deck-level; no substory_id; not in any substory's
    #    slide_ids list; spliced between title and S1 divider).
    for intro_slide in intro_slides:
        cleaned = strip_orchestrator_metadata(intro_slide)
        # intro slides also have an `intro_role` field that's
        # orchestrator metadata, not in slide_spec — strip it.
        cleaned.pop("intro_role", None)
        cleaned["id"] = next_id
        # Intro slides have no substory_id; clear if present (defensive)
        cleaned.pop("substory_id", None)
        slides.append(cleaned)
        next_id += 1

    # 3. Per-substory slides (in declared order)
    speaker_notes_dir = (Path(args.speaker_notes_dir)
                         if args.speaker_notes_dir else None)
    n_notes_injected = 0
    for substory in substories:
        sid = substory["id"]
        fragment = fragments[sid]
        # 2026-04-27 #70: load parsed speaker notes for this substory
        # (if speaker_notes stage ran). Notes are keyed by per-substory
        # position (0-indexed within fragment.slides).
        notes_for_substory = load_speaker_notes_for_substory(
            speaker_notes_dir, sid
        )
        for fragment_position, slide in enumerate(fragment["slides"]):
            cleaned = strip_orchestrator_metadata(slide)
            cleaned["id"] = next_id
            cleaned["substory_id"] = sid
            substory["slide_ids"].append(next_id)
            # Inject speaker_notes for this position if available
            if fragment_position in notes_for_substory:
                cleaned["speaker_notes"] = notes_for_substory[fragment_position]
                n_notes_injected += 1
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

    print(f"  -> merged {len(slides)} slides "
          f"({len(intro_slides)} intro + per-substory across "
          f"{len(substories)} substories)", file=sys.stderr)
    if n_notes_injected > 0:
        print(f"  -> injected speaker_notes on {n_notes_injected} slide(s)",
              file=sys.stderr)
    print(f"     wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
