"""Tests for the smoke orchestrator's Python helpers.

Covers:
  - parse_throughline_candidates.py — section extraction, pick parsing
  - parse_substories.py — verdict + substory ID + punchline extraction
  - merge_compose_fragments.py — fragment merge + global ID assignment
                                  + stub boilerplate splice + schema
                                  conformance

These helpers are smoke-only (the production orchestrator may
restructure or replace them). The tests guard against regressions
during smoke iteration; they are not load-bearing for v0.1 release.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Path to the helpers under test
TOOLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src/beril_presentation_maker/skill/tools"
)

sys.path.insert(0, str(TOOLS_DIR))

import merge_compose_fragments as mcf  # noqa: E402
import parse_substories as ps  # noqa: E402
import parse_throughline_candidates as ptc  # noqa: E402
import slide_spec  # noqa: E402


# ----------------------------------------------------------------------
# parse_throughline_candidates tests
# ----------------------------------------------------------------------

CANDIDATES_FIXTURE = """\
# Throughline candidates — `functional_dark_matter` / talk-30

**Tier:** STRONG

## TL1 — Inner-loop annotation outperforms RAST one-shot on Morgan Price gold standard

**Evidence map:**
- ✓ A1: 138/142 recovery (REPORT §3.2)
- ⚠ A3: cross-organism scope unverified

**Slide-count estimate:** 18 slides (talk-30 STRONG)

## TL2 — Methods comparison shows pipeline-design choices dominate accuracy

**Evidence map:**
- ✓ A2: ablation study results
- ⚠ A4: single-replicate caveat

**Slide-count estimate:** 22 slides

## TL3 — Implications for community resequencing pipelines

**Evidence map:**
- ◇ A5: inferred from related work
"""


def test_parse_throughline_extract_TL1():
    section = ptc.extract_candidate_section(CANDIDATES_FIXTURE, "TL1")
    assert section is not None
    assert section.startswith("## TL1 — Inner-loop annotation")
    assert "## TL2" not in section, "section must stop before next H2"
    assert "138/142 recovery" in section


def test_parse_throughline_extract_TL3_to_eof():
    section = ptc.extract_candidate_section(CANDIDATES_FIXTURE, "TL3")
    assert section is not None
    assert section.startswith("## TL3 — Implications")
    assert "A5: inferred" in section


def test_parse_throughline_missing_pick():
    section = ptc.extract_candidate_section(CANDIDATES_FIXTURE, "TL99")
    assert section is None


def test_parse_throughline_punchline():
    section = ptc.extract_candidate_section(CANDIDATES_FIXTURE, "TL1")
    assert section is not None
    pl = ptc.parse_candidate_punchline(section)
    assert pl == "Inner-loop annotation outperforms RAST one-shot on Morgan Price gold standard"


def test_parse_throughline_cli_writes_file(tmp_path: Path):
    candidates_file = tmp_path / "00_throughline_candidates.md"
    candidates_file.write_text(CANDIDATES_FIXTURE, encoding="utf-8")
    out_file = tmp_path / "00_throughline.md"

    rc = subprocess.run(
        [sys.executable,
         str(TOOLS_DIR / "parse_throughline_candidates.py"),
         "--candidates", str(candidates_file),
         "--pick", "TL2",
         "--out", str(out_file)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr

    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "<!-- chosen: TL2 -->" in content
    assert "<!-- punchline: Methods comparison" in content
    assert "## TL2 — Methods comparison" in content
    # Should not contain TL1 or TL3 sections
    assert "## TL1" not in content
    assert "## TL3" not in content


# Fixtures for the four header variants we've observed in live output
# (live throughline.v1 produced the "Candidate TL1: ..." shape on
# 2026-04-26; the parser must absorb all four).

CANDIDATES_VARIANT_COLON = """\
## TL1: First claim text here.

Body 1.

## TL2: Second claim.

Body 2.
"""

CANDIDATES_VARIANT_PREFIX_EMDASH = """\
## Candidate TL1 — First claim text here.

Body 1.

## Candidate TL2 — Second claim.

Body 2.
"""

CANDIDATES_VARIANT_PREFIX_COLON = """\
## Candidate TL1: First claim text here.

Body 1.

## Candidate TL2: Second claim.

Body 2.
"""


@pytest.mark.parametrize("fixture,expected_punch", [
    (CANDIDATES_VARIANT_COLON, "First claim text here."),
    (CANDIDATES_VARIANT_PREFIX_EMDASH, "First claim text here."),
    (CANDIDATES_VARIANT_PREFIX_COLON, "First claim text here."),
])
def test_parse_throughline_tolerates_header_variants(fixture, expected_punch):
    section = ptc.extract_candidate_section(fixture, "TL1")
    assert section is not None, f"failed to find TL1 in: {fixture[:60]!r}"
    pl = ptc.parse_candidate_punchline(section)
    assert pl == expected_punch


def test_parse_throughline_real_world_fixture():
    """Regression for the 2026-04-26 live failure: the prompt produced
    `## Candidate TL2: ...` and the original regex didn't match it."""
    real_world = (
        "# Throughline Candidates — Functional Dark Matter\n\n"
        "## Candidate TL1: One in four bacterial genes lacks annotation.\n\n"
        "Body 1.\n\n"
        "## Candidate TL2: Convergent evidence enables prioritization.\n\n"
        "Body 2.\n\n"
        "## Candidate TL3: Phylogenetic gaps reveal expansion targets.\n\n"
        "Body 3.\n"
    )
    section = ptc.extract_candidate_section(real_world, "TL2")
    assert section is not None
    assert section.startswith("## Candidate TL2: Convergent evidence")
    assert "## Candidate TL3" not in section
    pl = ptc.parse_candidate_punchline(section)
    assert pl == "Convergent evidence enables prioritization."


def test_parse_throughline_invalid_pick_returns_1(tmp_path: Path):
    candidates_file = tmp_path / "candidates.md"
    candidates_file.write_text(CANDIDATES_FIXTURE, encoding="utf-8")
    out_file = tmp_path / "out.md"

    rc = subprocess.run(
        [sys.executable,
         str(TOOLS_DIR / "parse_throughline_candidates.py"),
         "--candidates", str(candidates_file),
         "--pick", "not-a-tl",
         "--out", str(out_file)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 1, rc.stderr


# ----------------------------------------------------------------------
# parse_substories tests
# ----------------------------------------------------------------------

SUBSTORY_FIXTURE_FITS = """\
# Substory clusters — `functional_dark_matter` / talk-30

**Throughline:** Inner-loop annotation outperforms RAST one-shot
**Tier:** STRONG
**Mode budget:** 22-32 slides

## Mode-capacity check

- Boilerplate slides: 7
- Per-substory content target: 3
- Required slides: 19
- Mode max: 32

**Capacity verdict:** `fits`

## Substory clusters

### S1 — Annotation comparison

**Punchline:** Inner-loop wins on the curated Morgan Price set.

**Critical analyses covered:**
- A1: recovery rate
- A3: timing comparison

### S2 — Limitations and scope

**Punchline:** Cross-organism scope is unverified; replication is in progress.

**Critical analyses covered:**
- A4: replication
"""


SUBSTORY_FIXTURE_OVERFLOW = """\
**Capacity verdict:** `overflow`

## Substory clusters

### S1 — Foo
**Punchline:** S1 punchline.

### S2 — Bar
**Punchline:** S2 punchline.

### S3 — Baz
**Punchline:** S3 punchline.

### S4 — Qux
**Punchline:** S4 punchline.
"""


def test_parse_substories_verdict_fits():
    v = ps.extract_capacity_verdict(SUBSTORY_FIXTURE_FITS)
    assert v == "fits"


def test_parse_substories_verdict_overflow():
    v = ps.extract_capacity_verdict(SUBSTORY_FIXTURE_OVERFLOW)
    assert v == "overflow"


def test_parse_substories_verdict_missing():
    v = ps.extract_capacity_verdict("# Random doc\n\nNo verdict here.\n")
    assert v is None


def test_parse_substories_ids_in_order():
    ids = ps.extract_substory_ids(SUBSTORY_FIXTURE_FITS)
    assert ids == ["S1", "S2"]


def test_parse_substories_ids_overflow():
    ids = ps.extract_substory_ids(SUBSTORY_FIXTURE_OVERFLOW)
    assert ids == ["S1", "S2", "S3", "S4"]


def test_parse_substories_punchlines():
    pairs = ps.extract_substory_punchlines(SUBSTORY_FIXTURE_FITS)
    assert pairs == [
        ("S1", "Inner-loop wins on the curated Morgan Price set."),
        ("S2", "Cross-organism scope is unverified; replication is in progress."),
    ]


def test_parse_substories_cli_verdict(tmp_path: Path):
    f = tmp_path / "02_substories.md"
    f.write_text(SUBSTORY_FIXTURE_FITS, encoding="utf-8")

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "parse_substories.py"),
         "--path", str(f), "--field", "capacity_verdict"],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr
    assert rc.stdout.strip() == "fits"


def test_parse_substories_cli_substory_ids(tmp_path: Path):
    f = tmp_path / "02_substories.md"
    f.write_text(SUBSTORY_FIXTURE_OVERFLOW, encoding="utf-8")

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "parse_substories.py"),
         "--path", str(f), "--field", "substory_ids"],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr
    assert rc.stdout.strip() == "S1 S2 S3 S4"


# ----------------------------------------------------------------------
# merge_compose_fragments tests
# ----------------------------------------------------------------------

THROUGHLINE_MD = """\
<!-- chosen: TL1 -->
<!-- punchline: Inner-loop wins on Morgan Price gold standard -->

# Throughline (chosen: TL1)

## TL1 — Inner-loop wins on Morgan Price gold standard

**Tier:** STRONG

Body content.
"""


def _make_fragment_S1() -> dict:
    """Synthetic compose-fragment.v1 for S1 with divider + 2 content slides."""
    return {
        "schema_version": "compose-fragment.v1",
        "substory_id": "S1",
        "substory_punchline": "Inner-loop wins on the curated Morgan Price set.",
        "throughline_id": "TL1",
        "mode": "talk-30",
        "tier": "STRONG",
        "slides": [
            {
                "position": 0,
                "layout": "section_divider",
                "content": {
                    "punchline": "Inner-loop wins on the curated Morgan Price set.",
                    "substory_number": 1,
                },
                "speaker_notes_seed": "(seed; will be dropped on smoke merge)",
                "evidence_anchors": [
                    {"kind": "report_section", "ref": "REPORT.md §3"},
                ],
            },
            {
                "position": 1,
                "layout": "claim_evidence",
                "content": {
                    "title": "Inner-loop annotation: 138/142 recovery on Morgan Price",
                    "bullets": [
                        "Morgan Price gold standard: 142 biosynthesis loci",
                        "Inner-loop recovery: 138/142 (97.2%)",
                        "Cross-replicate variance: ±0.4 pp",
                    ],
                },
                "speaker_notes_seed": "(seed)",
                "evidence_anchors": [
                    {"kind": "report_section", "ref": "REPORT.md §3.2"},
                ],
            },
        ],
    }


def _make_fragment_S2() -> dict:
    return {
        "schema_version": "compose-fragment.v1",
        "substory_id": "S2",
        "substory_punchline": "Cross-organism scope is unverified.",
        "throughline_id": "TL1",
        "mode": "talk-30",
        "tier": "STRONG",
        "slides": [
            {
                "position": 0,
                "layout": "section_divider",
                "content": {
                    "punchline": "Cross-organism scope is unverified.",
                    "substory_number": 2,
                },
                "speaker_notes_seed": "(seed)",
                "evidence_anchors": [],
            },
            {
                "position": 1,
                "layout": "implications",
                "content": {
                    "title": "What we don't yet know",
                    "bullets": [
                        {
                            "claim": "Recovery may be lower on uncharacterized loci.",
                            "evidence_pointer": "REPORT.md §4.1",
                        },
                    ],
                },
            },
        ],
    }


def test_merge_writes_valid_slide_spec(tmp_path: Path):
    # Set up the inputs the merge expects
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()

    throughline_path = outdir / "00_throughline.md"
    throughline_path.write_text(THROUGHLINE_MD, encoding="utf-8")

    substory_path = outdir / "02_substories.md"
    substory_path.write_text(SUBSTORY_FIXTURE_FITS, encoding="utf-8")

    (outdir / "03_slides" / "S1_slides.json").write_text(
        json.dumps(_make_fragment_S1()), encoding="utf-8",
    )
    (outdir / "03_slides" / "S2_slides.json").write_text(
        json.dumps(_make_fragment_S2()), encoding="utf-8",
    )

    out_path = outdir / "slide_spec.json"

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "merge_compose_fragments.py"),
         "--outdir", str(outdir),
         "--project-id", "functional_dark_matter",
         "--mode", "talk-30",
         "--tier", "STRONG",
         "--audience", "peer",
         "--throughline-path", str(throughline_path),
         "--substory-path", str(substory_path),
         "--fragments-dir", str(outdir / "03_slides"),
         "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr

    spec = json.loads(out_path.read_text(encoding="utf-8"))

    # Top-level shape
    assert spec["schema_version"] == slide_spec.SCHEMA_VERSION
    assert spec["project_id"] == "functional_dark_matter"
    assert spec["mode"] == "talk-30"
    assert spec["tier"] == "STRONG"
    assert spec["audience"] == "peer"
    assert spec["throughline"]["id"] == "TL1"
    assert spec["throughline"]["punchline"] == \
        "Inner-loop wins on Morgan Price gold standard"

    # Slide ordering: title (1), S1 divider (2), S1 content (3), S2 divider (4),
    # S2 content (5), acknowledgments (6), references (7)
    slides = spec["slides"]
    assert len(slides) == 7
    assert slides[0]["layout"] == "title"
    assert slides[0]["id"] == 1
    assert slides[1]["layout"] == "section_divider"
    assert slides[1]["substory_id"] == "S1"
    assert slides[2]["layout"] == "claim_evidence"
    assert slides[2]["substory_id"] == "S1"
    assert slides[3]["layout"] == "section_divider"
    assert slides[3]["substory_id"] == "S2"
    assert slides[4]["layout"] == "implications"
    assert slides[4]["substory_id"] == "S2"
    assert slides[5]["layout"] == "acknowledgments"
    assert slides[6]["layout"] == "references"

    # Substory metadata: slide_ids populated
    s1 = next(s for s in spec["substories"] if s["id"] == "S1")
    s2 = next(s for s in spec["substories"] if s["id"] == "S2")
    assert s1["slide_ids"] == [2, 3]
    assert s2["slide_ids"] == [4, 5]

    # Speaker_notes_seed and evidence_anchors should NOT be on merged slides
    for s in slides[1:5]:  # the substory-derived slides
        assert "speaker_notes_seed" not in s
        assert "evidence_anchors" not in s
        assert "position" not in s

    # Validate against slide_spec contract
    issues = slide_spec.validate_slide_spec(spec)
    assert issues == [], "merged spec must validate; got: " + \
        "\n  ".join(i.format() for i in issues)


def test_merge_fails_on_missing_fragment(tmp_path: Path):
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()

    throughline_path = outdir / "00_throughline.md"
    throughline_path.write_text(THROUGHLINE_MD, encoding="utf-8")

    substory_path = outdir / "02_substories.md"
    substory_path.write_text(SUBSTORY_FIXTURE_FITS, encoding="utf-8")

    # S1 fragment present, S2 fragment missing
    (outdir / "03_slides" / "S1_slides.json").write_text(
        json.dumps(_make_fragment_S1()), encoding="utf-8",
    )

    out_path = outdir / "slide_spec.json"

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "merge_compose_fragments.py"),
         "--outdir", str(outdir),
         "--project-id", "p",
         "--mode", "talk-30",
         "--tier", "STRONG",
         "--audience", "peer",
         "--throughline-path", str(throughline_path),
         "--substory-path", str(substory_path),
         "--fragments-dir", str(outdir / "03_slides"),
         "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 3, f"expected exit 3 (missing fragment), got {rc.returncode}: {rc.stderr}"
    assert "fragment missing for substory S2" in rc.stderr or \
           "S2_slides.json" in rc.stderr


def test_merge_fails_on_bad_throughline(tmp_path: Path):
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()

    # Throughline file exists but has no `chosen` metadata comment
    throughline_path = outdir / "00_throughline.md"
    throughline_path.write_text("# Throughline\n\nNo metadata.\n", encoding="utf-8")

    substory_path = outdir / "02_substories.md"
    substory_path.write_text(SUBSTORY_FIXTURE_FITS, encoding="utf-8")

    out_path = outdir / "slide_spec.json"

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "merge_compose_fragments.py"),
         "--outdir", str(outdir),
         "--project-id", "p",
         "--mode", "talk-30",
         "--tier", "STRONG",
         "--audience", "peer",
         "--throughline-path", str(throughline_path),
         "--substory-path", str(substory_path),
         "--fragments-dir", str(outdir / "03_slides"),
         "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 2, f"expected exit 2 (bad throughline), got {rc.returncode}: {rc.stderr}"
