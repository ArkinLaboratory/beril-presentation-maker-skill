#!/usr/bin/env python3
"""parse_speaker_notes.py — parse speaker_notes.v1.md output into JSON.

The speaker_notes.v1 prompt writes markdown with the strict H2 header
format:

    ## position {N} — {layout} — `{title-or-punchline}`

    {200–400 word body}

    ---

    ## position {N+1} — ...

This script reads such a file and produces a JSON dict mapping
position (0-indexed) to body text:

    {
      "substory_id": "S1",
      "notes_by_position": {
        "0": "<text...>",
        "1": "<text...>",
        ...
      }
    }

Used by the orchestrator's merge step to inject speaker notes into
final slide_spec.json's per-slide `speaker_notes` field.

CLI:

    python3 parse_speaker_notes.py \\
        --notes <path/to/{substory_id}_speaker_notes.md> \\
        --out <path/to/{substory_id}_notes.json>

Exit codes:
  0 — parsed successfully
  1 — input file missing / unreadable
  2 — header format violation (no recognized H2 sections)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Match `## position N — LAYOUT — `title`` (em-dash; backticked title).
# Tolerates em-dash / en-dash / hyphen as separator (live LLM drift).
HEADER_RE = re.compile(
    r"^## position (\d+)\s*[—–-]\s*(\w+)\s*[—–-]\s*`(.+?)`\s*$",
    re.MULTILINE,
)

# Match the substory_id from the H1 frontmatter
SUBSTORY_ID_RE = re.compile(
    r"^# Speaker notes\s*[—–-]\s*substory\s*`([^`]+)`",
    re.MULTILINE,
)


def parse_speaker_notes_md(text: str) -> dict:
    """Parse the markdown into a structured dict.

    Returns:
      {
        "substory_id": "<id>" or None,
        "notes_by_position": {position_int: body_str, ...},
        "header_count": int,
      }
    """
    # Pull substory_id from H1
    sid_match = SUBSTORY_ID_RE.search(text)
    substory_id = sid_match.group(1) if sid_match else None

    # Find all H2 section headers
    headers = list(HEADER_RE.finditer(text))
    notes_by_position: dict[int, str] = {}

    for i, m in enumerate(headers):
        position = int(m.group(1))
        body_start = m.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[body_start:body_end]
        # Strip leading newlines + any `---` separator at the end of body
        body = body.strip()
        # Drop trailing `---` (section separator) if present
        body = re.sub(r"\n---\s*$", "", body).strip()
        notes_by_position[position] = body

    return {
        "substory_id": substory_id,
        "notes_by_position": notes_by_position,
        "header_count": len(headers),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes", required=True,
                    help="Path to {substory_id}_speaker_notes.md")
    ap.add_argument("--out", required=True,
                    help="Output path for the parsed JSON")
    args = ap.parse_args()

    notes_path = Path(args.notes)
    if not notes_path.is_file():
        print(f"Error: notes file not found: {notes_path}", file=sys.stderr)
        return 1

    try:
        text = notes_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error: cannot read {notes_path}: {e}", file=sys.stderr)
        return 1

    parsed = parse_speaker_notes_md(text)

    if parsed["header_count"] == 0:
        print(f"Error: no recognized H2 headers in {notes_path}",
              file=sys.stderr)
        print(f"  expected format: '## position {{N}} — {{layout}} — `{{title}}`'",
              file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Convert int keys to strings for JSON
    parsed["notes_by_position"] = {
        str(k): v for k, v in parsed["notes_by_position"].items()
    }
    out_path.write_text(
        json.dumps(parsed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"  -> parsed {parsed['header_count']} sections → {out_path}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
