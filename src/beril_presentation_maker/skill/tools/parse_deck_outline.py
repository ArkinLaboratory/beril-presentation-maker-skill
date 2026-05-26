#!/usr/bin/env python3
"""parse_deck_outline.py — extract the v0.4 deck-outline fields from
the enriched ``02_substories.md``.

``deck_outline.v1.md`` (v0.4 M2 — V0_4_ARCHITECTURE.md §20) writes an
*enriched* ``02_substories.md``: the v0.3.x substory skeleton — still
parsed by ``parse_substories.py``, which is deliberately left
untouched — PLUS the v0.4 cross-section-coordination fields. This
helper extracts the new fields; ``parse_substories.py`` extracts the
carried skeleton (substory ids, punchlines, capacity verdict).

Deck-level fields (one value each, from the ``## Deck-level spec``
block):

  --field register       the deck register / voice spec
  --field arc            the deck arc (how the sections earn each other)
  --field image_budget   the deck-wide image budget

Per-section fields (one ``S{N}\\t<value>`` line per substory, in
document order; a section missing the field emits an empty value):

  --field budgets         per-section slide budget
  --field headline_slots  per-section big_number headline slot
  --field transitions_in  per-section transition-in sentence
  --field transitions_out per-section transition-out sentence
  --field scoped_figures  per-section scoped figure ids

Exit codes:
  0 — success
  1 — file missing / unreadable
  2 — field could not be parsed (deck-level field absent, or no
      substory sections found for a per-section field)

Test coverage: tests/unit/test_parse_deck_outline.py — includes a
backward-compat check that ``parse_substories.py`` still parses the
same enriched file.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Same substory header shape parse_substories.py uses — `### S1 — name`.
SUBSTORY_HEADER_RE = re.compile(
    r"^### (S\d+)\s*[—–-]\s*(.+?)\s*$",
    re.MULTILINE,
)

# Per-section bold-label fields: --field name -> markdown label.
_SECTION_FIELDS = {
    "budgets": "Budget",
    "headline_slots": "Headline slot",
    "transitions_in": "Transition in",
    "transitions_out": "Transition out",
    "scoped_figures": "Scoped figures",
    # v0.5 D-071: Q/A/R/C contract fields per substory. Question is
    # required on every substory; Conclusion is required on every
    # non-final substory (empty string returned for last substory's
    # missing Conclusion — caller decides whether to treat as error).
    "questions": "Question",
    "conclusions": "Conclusion for next substory",
}

# Deck-level bold-label fields (single occurrence, in ## Deck-level spec).
_DECK_FIELDS = {
    "register": "Register",
    "arc": "Arc",
    "image_budget": "Image budget",
}


def _field_re(label: str) -> re.Pattern:
    """Regex matching a single ``**{label}:** value`` line."""
    return re.compile(
        r"^\*\*" + re.escape(label) + r":\*\*\s*(.+?)\s*$",
        re.MULTILINE,
    )


def extract_deck_field(content: str, label: str) -> str | None:
    """Return the first ``**{label}:** value`` in the document, or None.

    Deck-level labels (Register / Arc / Image budget) are distinct from
    the per-section labels, so a document-wide search is unambiguous.
    """
    m = _field_re(label).search(content)
    return m.group(1).strip() if m else None


def _section_spans(content: str) -> list[tuple[str, int, int]]:
    """Return ``[(substory_id, body_start, body_end), ...]`` in document
    order — each span is the text between one ``### S{N} —`` header and
    the next (or end of document)."""
    headers = list(SUBSTORY_HEADER_RE.finditer(content))
    spans: list[tuple[str, int, int]] = []
    for i, m in enumerate(headers):
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        spans.append((m.group(1), start, end))
    return spans


def extract_section_field(content: str, label: str) -> list[tuple[str, str]]:
    """Return ``[(substory_id, value), ...]`` for the ``**{label}:**``
    line inside each substory section, in document order.

    A section that omits the field yields value ``""`` — the caller
    decides whether a missing per-section field is an error.
    """
    field_re = _field_re(label)
    out: list[tuple[str, str]] = []
    for sid, start, end in _section_spans(content):
        m = field_re.search(content[start:end])
        out.append((sid, m.group(1).strip() if m else ""))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="parse_deck_outline.py",
        description=(
            "Extract v0.4 deck-outline fields from an enriched "
            "02_substories.md. Carried skeleton fields (substory ids, "
            "punchlines, capacity verdict) stay with parse_substories.py."
        ),
    )
    ap.add_argument("--path", required=True,
                    help="Path to the enriched 02_substories.md")
    ap.add_argument(
        "--field", required=True,
        choices=sorted([*_DECK_FIELDS, *_SECTION_FIELDS]),
        help="Which field to extract",
    )
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.is_file():
        print(f"Error: deck outline not found: {path}", file=sys.stderr)
        return 1
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error: cannot read {path}: {e}", file=sys.stderr)
        return 1

    if args.field in _DECK_FIELDS:
        val = extract_deck_field(content, _DECK_FIELDS[args.field])
        if val is None:
            print(f"Error: could not parse '{args.field}' "
                  f"(**{_DECK_FIELDS[args.field]}:**) from {path}",
                  file=sys.stderr)
            return 2
        print(val)
        return 0

    label = _SECTION_FIELDS[args.field]
    pairs = extract_section_field(content, label)
    if not pairs:
        print(f"Error: no substory sections (### S{{N}} — ...) found "
              f"in {path}", file=sys.stderr)
        return 2
    for sid, val in pairs:
        print(f"{sid}\t{val}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
