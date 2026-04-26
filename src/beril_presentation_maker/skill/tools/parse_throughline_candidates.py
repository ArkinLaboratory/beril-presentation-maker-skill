#!/usr/bin/env python3
"""parse_throughline_candidates.py — pick one throughline candidate and
write the canonical 00_throughline.md.

Reads `00_throughline_candidates.md` produced by `throughline.v1.md`,
finds the section matching `--pick` (e.g., `TL1`, `TL2`, `TL3`),
extracts the candidate's full section (from the H2 header to the next
H2 or EOF), and writes it to `--out` with a frontmatter line declaring
the chosen ID.

Used by the smoke orchestrator's throughline pick gate. The orchestrator
either prompts the user interactively or auto-picks `TL1` in
`--auto-advance` mode; this script does the actual file rewrite.

CLI:
    python3 parse_throughline_candidates.py \
        --candidates path/to/00_throughline_candidates.md \
        --pick TL1 \
        --out path/to/00_throughline.md

Exit codes:
  0 — success; 00_throughline.md written
  1 — pick not found in candidates file
  2 — candidates file missing or malformed
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract_candidate_section(content: str, pick: str) -> str | None:
    """Find the markdown section whose H2 header introduces the picked
    throughline. Tolerates the four variants we've observed in live
    throughline.v1 output:

      ## TL1 — claim                       (originally specified)
      ## TL1: claim                        (colon variant)
      ## Candidate TL1 — claim             (Candidate-prefix + em-dash)
      ## Candidate TL1: claim              (Candidate-prefix + colon)
                                           ← what live LLM produced 2026-04-26

    The parser is tolerant; throughline.v1.md should still be tightened
    to require ONE format, but until that lands the parser absorbs the
    variation. Returns the full section from the H2 line through the
    line before the next H2 (or EOF), or None if the pick isn't found.
    """
    pattern = re.compile(
        rf"^## (?:Candidate\s+)?{re.escape(pick)}\s*[:—–-]\s*",
        re.MULTILINE,
    )
    m = pattern.search(content)
    if m is None:
        return None

    start = m.start()
    # Find the next H2 (any) starting after our match
    next_h2 = re.compile(r"^## ", re.MULTILINE)
    nm = next_h2.search(content, m.end())
    end = nm.start() if nm else len(content)

    return content[start:end].rstrip() + "\n"


def parse_candidate_punchline(section: str) -> str:
    """Pull the candidate's one-line claim from the H2 header.

    Examples (all four tolerated by extract_candidate_section above):
      `## TL1 — Inner-loop annotation outperforms RAST one-shot ...`
      `## TL1: Inner-loop annotation outperforms RAST one-shot ...`
      `## Candidate TL1 — Inner-loop annotation ...`
      `## Candidate TL1: Inner-loop annotation ...`
        →  `Inner-loop annotation ...`

    Returns empty string if it can't be parsed (defensive).
    """
    first_line = section.splitlines()[0] if section else ""
    m = re.match(
        r"^## (?:Candidate\s+)?TL\d+\s*[:—–-]\s*(.+?)\s*$",
        first_line,
    )
    return m.group(1) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True,
                    help="Path to 00_throughline_candidates.md")
    ap.add_argument("--pick", required=True,
                    help="Candidate to pick (TL1, TL2, TL3)")
    ap.add_argument("--out", required=True,
                    help="Output path for 00_throughline.md")
    args = ap.parse_args()

    candidates_path = Path(args.candidates)
    if not candidates_path.is_file():
        print(f"Error: candidates file not found: {candidates_path}",
              file=sys.stderr)
        return 2

    try:
        content = candidates_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error: cannot read {candidates_path}: {e}", file=sys.stderr)
        return 2

    if not content.strip():
        print(f"Error: candidates file is empty: {candidates_path}",
              file=sys.stderr)
        return 2

    pick = args.pick.strip().upper()
    if not re.match(r"^TL\d+$", pick):
        print(f"Error: --pick must be of the form TL<digit>, got '{pick}'",
              file=sys.stderr)
        return 1

    section = extract_candidate_section(content, pick)
    if section is None:
        print(f"Error: candidate {pick} not found in {candidates_path}",
              file=sys.stderr)
        return 1

    punchline = parse_candidate_punchline(section)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        f"<!-- chosen: {pick} -->\n"
        f"<!-- punchline: {punchline} -->\n\n"
        f"# Throughline (chosen: {pick})\n\n"
        f"_Picked from `00_throughline_candidates.md` by the smoke "
        f"orchestrator's throughline gate._\n\n"
        f"---\n\n"
    )
    out_path.write_text(header + section, encoding="utf-8")

    print(f"  -> wrote {out_path} (chose {pick}: {punchline[:60]}...)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
