#!/usr/bin/env python3
"""parse_substories.py — extract structured fields from 02_substories.md.

The substory_design.v1.md prompt produces a structured markdown file
with a known shape (per the prompt's "Output format" section):

    # Substory clusters — `<project>` / talk mode `<mode>`

    **Throughline:** ...
    **Tier:** ...
    **Mode budget:** ...

    ## Mode-capacity check
    ...
    **Capacity verdict:** `fits` | `overflow` | `under-utilized`

    ## Substory clusters

    ### S1 — name
    **Punchline:** ...
    ...
    ### S2 — name
    ...

This helper extracts:
  --field capacity_verdict   →  "fits" | "overflow" | "under-utilized"
  --field substory_ids       →  space-separated list (e.g., "S1 S2 S3")
  --field substory_punchlines  →  one-per-line "S1\\t<punchline>"

Used by the smoke orchestrator to gate on overflow + drive the
slide_compose loop.

Exit codes:
  0 — success
  1 — file missing / unreadable
  2 — field could not be parsed
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERDICT_RE = re.compile(
    r"^\*\*Capacity verdict:\*\*\s*`?([\w-]+)`?",
    re.MULTILINE,
)

SUBSTORY_HEADER_RE = re.compile(
    r"^### (S\d+)\s*[—–-]\s*(.+?)\s*$",
    re.MULTILINE,
)

PUNCHLINE_RE = re.compile(
    r"^\*\*Punchline:\*\*\s*(.+?)\s*$",
    re.MULTILINE,
)


def extract_capacity_verdict(content: str) -> str | None:
    m = VERDICT_RE.search(content)
    if m is None:
        return None
    val = m.group(1).strip().lower()
    if val not in ("fits", "overflow", "under-utilized"):
        return None
    return val


def extract_substory_ids(content: str) -> list[str]:
    """Return substory IDs in document order. Deduplicates while
    preserving first-seen order (defensive; the prompt should not
    produce duplicates)."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for m in SUBSTORY_HEADER_RE.finditer(content):
        sid = m.group(1)
        if sid not in seen_set:
            seen.append(sid)
            seen_set.add(sid)
    return seen


def extract_substory_punchlines(content: str) -> list[tuple[str, str]]:
    """Return [(id, punchline), ...] in document order.

    Walks the substory cluster sections and pulls the **Punchline:**
    line that follows each `### S{N} — ` header.
    """
    out: list[tuple[str, str]] = []
    # Find each substory header and the following section
    headers = list(SUBSTORY_HEADER_RE.finditer(content))
    for i, m in enumerate(headers):
        sid = m.group(1)
        section_start = m.end()
        section_end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        section = content[section_start:section_end]
        pm = PUNCHLINE_RE.search(section)
        punchline = pm.group(1).strip() if pm else ""
        out.append((sid, punchline))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True,
                    help="Path to 02_substories.md")
    ap.add_argument("--field", required=True,
                    choices=("capacity_verdict", "substory_ids",
                             "substory_punchlines"),
                    help="Which field to extract")
    args = ap.parse_args()

    path = Path(args.path)
    if not path.is_file():
        print(f"Error: substories file not found: {path}", file=sys.stderr)
        return 1

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error: cannot read {path}: {e}", file=sys.stderr)
        return 1

    if args.field == "capacity_verdict":
        verdict = extract_capacity_verdict(content)
        if verdict is None:
            print(f"Error: could not parse capacity verdict from {path}",
                  file=sys.stderr)
            return 2
        print(verdict)
        return 0

    if args.field == "substory_ids":
        ids = extract_substory_ids(content)
        if not ids:
            print(f"Error: no substory IDs (### S{{N}} — ...) found in {path}",
                  file=sys.stderr)
            return 2
        print(" ".join(ids))
        return 0

    if args.field == "substory_punchlines":
        pairs = extract_substory_punchlines(content)
        if not pairs:
            print(f"Error: no substory punchlines parsed from {path}",
                  file=sys.stderr)
            return 2
        for sid, pl in pairs:
            print(f"{sid}\t{pl}")
        return 0

    return 2


def audit_punchline_lengths(content: str, recommended_max_words: int = 14) -> list[tuple[str, str, int]]:
    """Audit substory punchline lengths against the recommendation.

    Returns list of (substory_id, punchline, word_count) for each
    substory whose punchline EXCEEDS recommended_max_words. Empty
    list = all punchlines within recommendation.

    2026-04-27 #79: substory_design.v1's word cap is soft; this
    audit gives the orchestrator visibility into whether the
    discipline held without making it validator-blocking.
    """
    pairs = extract_substory_punchlines(content)
    over = []
    for sid, punchline in pairs:
        word_count = len(punchline.split())
        if word_count > recommended_max_words:
            over.append((sid, punchline, word_count))
    return over


if __name__ == "__main__":
    sys.exit(main())
