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
    # 2026-04-26 fix #52: title slide uses project_id title-case, NOT the
    # throughline punchline (which would overrun the title placeholder 5x).
    # Throughline punchline lives in the subtitle field instead.
    assert slides[0]["content"]["title"] == "Functional Dark Matter"
    assert slides[0]["content"].get("subtitle") == \
        "Inner-loop wins on Morgan Price gold standard"
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
    # (per-slide compose-fragment metadata; stripped at merge time).
    for s in slides[1:5]:  # the substory-derived slides
        assert "speaker_notes_seed" not in s
        assert "evidence_anchors" not in s

    # v0.3.2.1: merge populates `position` (1-based) on every slide so
    # the revise loop's add_slide path can do surgical insertion. Verify
    # all merged slides have an integer position matching their array
    # index + 1.
    for idx, s in enumerate(slides, start=1):
        assert s.get("position") == idx, (
            f"slide at idx {idx} (id={s.get('id')}, layout={s.get('layout')}) "
            f"has position={s.get('position')!r}; expected {idx}"
        )

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


# ----------------------------------------------------------------------
# Intro fragment splicing tests (added 2026-04-26 with intro architecture)
# ----------------------------------------------------------------------

def _make_intro_fragment() -> dict:
    """Synthetic talk-30 intro fragment: 3 slides covering background,
    goal, and approach. Mirrors the shape intro.v1.md will produce."""
    return {
        "schema_version": "compose-fragment.v1",
        "kind": "intro",
        "throughline_id": "TL1",
        "mode": "talk-30",
        "tier": "STRONG",
        "n_intro_slides_target": 3,
        "slides": [
            {
                "position": 0,
                "layout": "big_idea",
                "content": {
                    "title": "One in four bacterial genes lacks functional annotation",
                },
                "speaker_notes_seed": "(seed)",
                "evidence_anchors": [
                    {"kind": "report_section", "ref": "REPORT.md §Finding 1"},
                ],
                "intro_role": "background",
            },
            {
                "position": 1,
                "layout": "claim_evidence",
                "content": {
                    "title": "Goal: identify experimentally actionable dark genes",
                    "bullets": [
                        "Score 57,011 dark genes across 48 organisms",
                        "Validate via cross-organism conservation",
                        "Produce a tractable RB-TnSeq experimental roadmap",
                    ],
                },
                "speaker_notes_seed": "(seed)",
                "evidence_anchors": [
                    {"kind": "report_section", "ref": "RESEARCH_PLAN.md §H1"},
                ],
                "intro_role": "goal",
            },
            {
                "position": 2,
                "layout": "methods_summary",
                "content": {
                    "title": "Approach: 3 evidence streams converge",
                    "bullets": [
                        "Census via fitness-effect distributions",
                        "Cross-organism conservation via 65 ortholog groups",
                        "Set-cover optimization across 47 RB-TnSeq libraries",
                        "Multi-dimensional scoring across 6 evidence axes",
                        "Pre-registered hypothesis testing with FDR correction",
                    ],
                },
                "speaker_notes_seed": "(seed)",
                "evidence_anchors": [
                    {"kind": "report_section", "ref": "REPORT.md §Methods"},
                ],
                "intro_role": "approach",
            },
        ],
    }


def test_merge_splices_intro_slides_between_title_and_S1(tmp_path: Path):
    """End-to-end: title (1) → intro × 3 (2,3,4) → S1 div+content (5,6) →
    S2 div+content (7,8) → ack (9) → ref (10) = 10 slides."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()

    (outdir / "00_throughline.md").write_text(
        THROUGHLINE_MD, encoding="utf-8")
    (outdir / "02_substories.md").write_text(
        SUBSTORY_FIXTURE_FITS, encoding="utf-8")
    (outdir / "03_slides" / "S1_slides.json").write_text(
        json.dumps(_make_fragment_S1()), encoding="utf-8")
    (outdir / "03_slides" / "S2_slides.json").write_text(
        json.dumps(_make_fragment_S2()), encoding="utf-8")
    intro_path = outdir / "03_slides" / "intro.json"
    intro_path.write_text(json.dumps(_make_intro_fragment()), encoding="utf-8")

    out_path = outdir / "slide_spec.json"

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "merge_compose_fragments.py"),
         "--outdir", str(outdir),
         "--project-id", "functional_dark_matter",
         "--mode", "talk-30",
         "--tier", "STRONG",
         "--audience", "peer",
         "--throughline-path", str(outdir / "00_throughline.md"),
         "--substory-path", str(outdir / "02_substories.md"),
         "--fragments-dir", str(outdir / "03_slides"),
         "--intro-fragment-path", str(intro_path),
         "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr

    spec = json.loads(out_path.read_text())

    # Slide ordering: title (1), intro × 3 (2,3,4), S1 div+content (5,6),
    # S2 div+content (7,8), ack (9), ref (10) = 10 slides.
    slides = spec["slides"]
    assert len(slides) == 10

    assert slides[0]["layout"] == "title"
    assert slides[0]["id"] == 1

    # Intro slides at positions 1-3 (ids 2-4); no substory_id;
    # intro_role stripped (orchestrator metadata not in slide_spec).
    assert slides[1]["layout"] == "big_idea"
    assert slides[1]["id"] == 2
    assert "substory_id" not in slides[1]
    assert "intro_role" not in slides[1]

    assert slides[2]["layout"] == "claim_evidence"
    assert slides[2]["id"] == 3
    assert "substory_id" not in slides[2]

    assert slides[3]["layout"] == "methods_summary"
    assert slides[3]["id"] == 4

    # S1 starts at slide id=5, S2 starts at id=7
    assert slides[4]["layout"] == "section_divider"
    assert slides[4]["substory_id"] == "S1"
    assert slides[4]["id"] == 5

    assert slides[6]["layout"] == "section_divider"
    assert slides[6]["substory_id"] == "S2"
    assert slides[6]["id"] == 7

    assert slides[8]["layout"] == "acknowledgments"
    assert slides[9]["layout"] == "references"

    # Substory slide_ids correctly track the post-intro IDs
    s1 = next(s for s in spec["substories"] if s["id"] == "S1")
    s2 = next(s for s in spec["substories"] if s["id"] == "S2")
    assert s1["slide_ids"] == [5, 6]
    assert s2["slide_ids"] == [7, 8]

    # Validate against slide_spec contract
    issues = slide_spec.validate_slide_spec(spec)
    assert issues == [], (
        "merged spec must validate; got:\n  "
        + "\n  ".join(i.format() for i in issues)
    )


def test_merge_handles_empty_intro_fragment_lightning_mode(tmp_path: Path):
    """Lightning-5 / poster modes emit empty intro fragment;
    merge should produce no intro slides (deck = title + substories +
    ack + ref)."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()

    (outdir / "00_throughline.md").write_text(
        THROUGHLINE_MD, encoding="utf-8")
    (outdir / "02_substories.md").write_text(
        SUBSTORY_FIXTURE_FITS, encoding="utf-8")
    (outdir / "03_slides" / "S1_slides.json").write_text(
        json.dumps(_make_fragment_S1()), encoding="utf-8")
    (outdir / "03_slides" / "S2_slides.json").write_text(
        json.dumps(_make_fragment_S2()), encoding="utf-8")

    # Empty intro fragment (lightning-5 / poster shape)
    empty_intro = {
        "schema_version": "compose-fragment.v1",
        "kind": "intro",
        "mode": "lightning-5",
        "tier": "STRONG",
        "n_intro_slides_target": 0,
        "slides": [],
    }
    intro_path = outdir / "03_slides" / "intro.json"
    intro_path.write_text(json.dumps(empty_intro), encoding="utf-8")

    out_path = outdir / "slide_spec.json"

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "merge_compose_fragments.py"),
         "--outdir", str(outdir),
         "--project-id", "functional_dark_matter",
         "--mode", "talk-30",  # talk-30 here just to get past validation
         "--tier", "STRONG",
         "--audience", "peer",
         "--throughline-path", str(outdir / "00_throughline.md"),
         "--substory-path", str(outdir / "02_substories.md"),
         "--fragments-dir", str(outdir / "03_slides"),
         "--intro-fragment-path", str(intro_path),
         "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr

    spec = json.loads(out_path.read_text())

    # 7 slides: title, S1 div, S1 content, S2 div, S2 content, ack, ref
    assert len(spec["slides"]) == 7
    assert spec["slides"][0]["layout"] == "title"
    assert spec["slides"][1]["layout"] == "section_divider"
    assert spec["slides"][1]["substory_id"] == "S1"


def test_merge_handles_missing_intro_fragment_path(tmp_path: Path):
    """If --intro-fragment-path is not passed, merge proceeds as if
    no intro stage ran. Smoke pre-intro behavior preserved."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()

    (outdir / "00_throughline.md").write_text(
        THROUGHLINE_MD, encoding="utf-8")
    (outdir / "02_substories.md").write_text(
        SUBSTORY_FIXTURE_FITS, encoding="utf-8")
    (outdir / "03_slides" / "S1_slides.json").write_text(
        json.dumps(_make_fragment_S1()), encoding="utf-8")
    (outdir / "03_slides" / "S2_slides.json").write_text(
        json.dumps(_make_fragment_S2()), encoding="utf-8")

    out_path = outdir / "slide_spec.json"

    # No --intro-fragment-path
    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "merge_compose_fragments.py"),
         "--outdir", str(outdir),
         "--project-id", "functional_dark_matter",
         "--mode", "talk-30",
         "--tier", "STRONG",
         "--audience", "peer",
         "--throughline-path", str(outdir / "00_throughline.md"),
         "--substory-path", str(outdir / "02_substories.md"),
         "--fragments-dir", str(outdir / "03_slides"),
         "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr

    spec = json.loads(out_path.read_text())
    assert len(spec["slides"]) == 7  # original behavior preserved


def test_merge_handles_malformed_intro_fragment(tmp_path: Path):
    """Malformed intro JSON should warn and proceed without intro,
    not crash the whole merge."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()

    (outdir / "00_throughline.md").write_text(
        THROUGHLINE_MD, encoding="utf-8")
    (outdir / "02_substories.md").write_text(
        SUBSTORY_FIXTURE_FITS, encoding="utf-8")
    (outdir / "03_slides" / "S1_slides.json").write_text(
        json.dumps(_make_fragment_S1()), encoding="utf-8")
    (outdir / "03_slides" / "S2_slides.json").write_text(
        json.dumps(_make_fragment_S2()), encoding="utf-8")

    # Malformed intro
    intro_path = outdir / "03_slides" / "intro.json"
    intro_path.write_text("{ this is not valid JSON",
                          encoding="utf-8")

    out_path = outdir / "slide_spec.json"

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "merge_compose_fragments.py"),
         "--outdir", str(outdir),
         "--project-id", "functional_dark_matter",
         "--mode", "talk-30",
         "--tier", "STRONG",
         "--audience", "peer",
         "--throughline-path", str(outdir / "00_throughline.md"),
         "--substory-path", str(outdir / "02_substories.md"),
         "--fragments-dir", str(outdir / "03_slides"),
         "--intro-fragment-path", str(intro_path),
         "--out", str(out_path)],
        capture_output=True, text=True,
    )
    # Should succeed (warn + proceed without intro), not fail
    assert rc.returncode == 0, rc.stderr
    assert "Warning" in rc.stderr or "warning" in rc.stderr

    spec = json.loads(out_path.read_text())
    assert len(spec["slides"]) == 7  # no intro slices, original 7 slides


# ----------------------------------------------------------------------
# parse_speaker_notes tests (Phase 2A.3 — 2026-04-27)
# ----------------------------------------------------------------------

import importlib.util as _ilu
_psn_spec = _ilu.spec_from_file_location(
    "parse_speaker_notes", TOOLS_DIR / "parse_speaker_notes.py"
)
_psn = _ilu.module_from_spec(_psn_spec)
_psn_spec.loader.exec_module(_psn)


SPEAKER_NOTES_FIXTURE = """\
# Speaker notes — substory `S1`

**Substory punchline:** Inner-loop wins on Morgan Price gold standard
**Throughline:** Inner-loop annotation outperforms one-shot RAST
**Tier:** STRONG
**Mode:** talk-30

---

## position 0 — section_divider — `Inner-loop wins`

This is the divider's notes. The substory opens by establishing the
core claim: inner-loop annotation outperforms RAST one-shot on the
curated Morgan Price gold standard.

---

## position 1 — methods_summary — `Methods: 3-pass refinement`

The methods slide explains the procedure. We start with RAST 2.0,
apply biosynthesis priors via inner-loop, and validate against
Morgan Price 2022 (n=142 biosynthesis loci).

---

## position 2 — claim_evidence — `97.2% recovery`

The headline result: 138/142 = 97.2% recovery. RAST one-shot only
recovered 109/142 = 76.8%. The 23-percentage-point gap is the
substory's load-bearing claim.
"""


def test_parse_speaker_notes_extracts_substory_id():
    result = _psn.parse_speaker_notes_md(SPEAKER_NOTES_FIXTURE)
    assert result["substory_id"] == "S1"


def test_parse_speaker_notes_captures_all_sections():
    result = _psn.parse_speaker_notes_md(SPEAKER_NOTES_FIXTURE)
    assert result["header_count"] == 3
    assert set(result["notes_by_position"].keys()) == {0, 1, 2}


def test_parse_speaker_notes_body_correct():
    result = _psn.parse_speaker_notes_md(SPEAKER_NOTES_FIXTURE)
    assert "RAST 2.0" in result["notes_by_position"][1]
    assert "138/142 = 97.2%" in result["notes_by_position"][2]
    # Trailing --- separator stripped
    assert not result["notes_by_position"][1].endswith("---")


def test_parse_speaker_notes_handles_dash_variants():
    """Live LLM may produce em-dash, en-dash, or hyphen in headers."""
    variants = [
        "## position 0 — section_divider — `T`\n\nBody.\n",
        "## position 0 – section_divider – `T`\n\nBody.\n",  # en-dash
        "## position 0 - section_divider - `T`\n\nBody.\n",
    ]
    for v in variants:
        r = _psn.parse_speaker_notes_md(v)
        assert r["header_count"] == 1, f"failed on variant: {v[:30]!r}"
        assert r["notes_by_position"][0].strip() == "Body."


def test_parse_speaker_notes_cli(tmp_path: Path):
    notes_file = tmp_path / "S1_speaker_notes.md"
    notes_file.write_text(SPEAKER_NOTES_FIXTURE, encoding="utf-8")
    out_file = tmp_path / "S1_notes.json"

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "parse_speaker_notes.py"),
         "--notes", str(notes_file),
         "--out", str(out_file)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr

    parsed = json.loads(out_file.read_text())
    assert parsed["substory_id"] == "S1"
    assert "0" in parsed["notes_by_position"]
    assert "1" in parsed["notes_by_position"]
    assert "2" in parsed["notes_by_position"]


def test_parse_speaker_notes_cli_fails_on_no_headers(tmp_path: Path):
    notes_file = tmp_path / "bad.md"
    notes_file.write_text("# Speaker notes\n\nNo H2 sections.\n",
                          encoding="utf-8")
    out_file = tmp_path / "out.json"

    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "parse_speaker_notes.py"),
         "--notes", str(notes_file),
         "--out", str(out_file)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 2, f"expected exit 2, got {rc.returncode}: {rc.stderr}"


def test_merge_injects_speaker_notes(tmp_path: Path):
    """End-to-end: merge with --speaker-notes-dir injects parsed notes
    into the appropriate per-substory slides."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    notes_dir = outdir / "04_speaker_notes"
    notes_dir.mkdir()

    (outdir / "00_throughline.md").write_text(
        THROUGHLINE_MD, encoding="utf-8")
    (outdir / "02_substories.md").write_text(
        SUBSTORY_FIXTURE_FITS, encoding="utf-8")
    (outdir / "03_slides" / "S1_slides.json").write_text(
        json.dumps(_make_fragment_S1()), encoding="utf-8")
    (outdir / "03_slides" / "S2_slides.json").write_text(
        json.dumps(_make_fragment_S2()), encoding="utf-8")

    # Pre-populate parsed notes for S1 (positions 0 + 1)
    (notes_dir / "S1_notes.json").write_text(json.dumps({
        "substory_id": "S1",
        "notes_by_position": {
            "0": "S1 divider notes — 30 words.",
            "1": "S1 content notes — 50 words.",
        },
    }), encoding="utf-8")

    out_path = outdir / "slide_spec.json"
    rc = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "merge_compose_fragments.py"),
         "--outdir", str(outdir),
         "--project-id", "test",
         "--mode", "talk-30",
         "--tier", "STRONG",
         "--audience", "peer",
         "--throughline-path", str(outdir / "00_throughline.md"),
         "--substory-path", str(outdir / "02_substories.md"),
         "--fragments-dir", str(outdir / "03_slides"),
         "--speaker-notes-dir", str(notes_dir),
         "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr
    # Stderr should report 2 notes injected
    assert "injected speaker_notes on 2" in rc.stderr

    spec = json.loads(out_path.read_text())
    s1_slides = [s for s in spec["slides"] if s.get("substory_id") == "S1"]
    assert len(s1_slides) == 2
    assert s1_slides[0]["speaker_notes"] == "S1 divider notes — 30 words."
    assert s1_slides[1]["speaker_notes"] == "S1 content notes — 50 words."

    # S2 has no notes file; should not have speaker_notes injected
    s2_slides = [s for s in spec["slides"] if s.get("substory_id") == "S2"]
    for s in s2_slides:
        assert "speaker_notes" not in s


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


# ---------------------------------------------------------------------------
# v0.3.2.1: lenient JSON loader strips trailing commas from LLM-emitted JSON
# ---------------------------------------------------------------------------

import importlib.util as _util


def _load_merge_module():
    spec = _util.spec_from_file_location(
        "merge_compose_fragments",
        TOOLS_DIR / "merge_compose_fragments.py",
    )
    module = _util.module_from_spec(spec)
    sys.modules["merge_compose_fragments"] = module
    spec.loader.exec_module(module)
    return module


def test_lenient_loader_passes_clean_json(tmp_path: Path):
    m = _load_merge_module()
    p = tmp_path / "clean.json"
    p.write_text('{"a": 1, "b": [1, 2, 3]}', encoding="utf-8")
    assert m._load_json_lenient(p) == {"a": 1, "b": [1, 2, 3]}


def test_lenient_loader_repairs_trailing_comma_in_array(tmp_path: Path, capsys):
    """Trailing comma after last array element → repair pass fixes it."""
    m = _load_merge_module()
    p = tmp_path / "dirty.json"
    p.write_text('{"a": 1, "b": [1, 2, 3,]}', encoding="utf-8")
    data = m._load_json_lenient(p)
    assert data == {"a": 1, "b": [1, 2, 3]}
    captured = capsys.readouterr()
    assert "stripped trailing comma" in captured.err


def test_lenient_loader_repairs_trailing_comma_in_object(tmp_path: Path, capsys):
    """Trailing comma after last object field → repair pass fixes it.

    This is the actual smoke-failure shape from core_gene_tradeoffs
    draft_2 — a `bullets` array closed cleanly, but the enclosing
    `content` object had a trailing comma before `}`.
    """
    m = _load_merge_module()
    p = tmp_path / "dirty.json"
    p.write_text(
        '{"slides": [{"layout": "claim_evidence", "content": {'
        '"title": "T", "bullets": ["a", "b"],}}]}',
        encoding="utf-8",
    )
    data = m._load_json_lenient(p)
    assert data["slides"][0]["content"]["title"] == "T"


def test_lenient_loader_handles_multiple_trailing_commas(tmp_path: Path):
    m = _load_merge_module()
    p = tmp_path / "dirty.json"
    p.write_text(
        '{"a": [1, 2,], "b": {"c": [3,], "d": "e",},}',
        encoding="utf-8",
    )
    data = m._load_json_lenient(p)
    assert data == {"a": [1, 2], "b": {"c": [3], "d": "e"}}


def test_lenient_loader_preserves_commas_inside_strings(tmp_path: Path):
    """The repair pass uses regex on the raw text — verify it doesn't
    accidentally strip commas that legitimately appear inside string
    values that happen to be followed by whitespace + `}` or `]`."""
    m = _load_merge_module()
    p = tmp_path / "ok.json"
    p.write_text(
        '{"msg": "hello, world", "items": ["a, b, c"]}',
        encoding="utf-8",
    )
    data = m._load_json_lenient(p)
    assert data["msg"] == "hello, world"
    assert data["items"] == ["a, b, c"]


def test_lenient_loader_raises_original_error_on_unrepairable(tmp_path: Path):
    """When the malformation is something OTHER than trailing commas
    (e.g., an unescaped quote inside a string value), the lenient
    loader raises the ORIGINAL JSONDecodeError so debug output points
    at the actual error."""
    m = _load_merge_module()
    p = tmp_path / "broken.json"
    # Unescaped quote in a string — unrepairable by the trailing-comma fix.
    p.write_text('{"msg": "he said "hi" to me"}', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        m._load_json_lenient(p)
