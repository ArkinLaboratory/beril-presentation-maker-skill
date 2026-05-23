"""Unit tests for tools/parse_deck_outline.py (v0.4 M2 Tier B).

Covers the v0.4 deck-outline field extractors plus a backward-compat
check that parse_substories.py still parses the carried skeleton in
the same enriched 02_substories.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from beril_presentation_maker.skill.tools import parse_deck_outline as pdo
from beril_presentation_maker.skill.tools import parse_substories as ps


# An enriched 02_substories.md as deck_outline.v1.md would emit it:
# the v0.3.x skeleton (### S{N} —, **Punchline:**, **Capacity verdict:**,
# **Critical analyses covered:**) PLUS the v0.4 coordination fields.
FIXTURE = """\
# Deck outline (substory clusters) — `ibd_phage_targeting` / talk mode `talk-30`

**Throughline:** TL1 — Ecotype-stratified microbiome analysis defines a hybrid phage-cocktail framework for Crohn's disease.
**Tier:** STRONG
**Mode budget:** 18-32 slides per SPEC §5

## Deck-level spec

**Register:** STRONG tier — assertive, quantitative; partial-evidence claims hedged on-slide.

**Arc:** Framework → targets → intervention: ecotypes make stratification possible, stratification makes confound-free targets possible.

**Image budget:** ≤2 AI concept illustrations deck-wide; data/procedural diagrams uncapped.

## Mode-capacity check

- **Boilerplate slides:** 7
- **Required slides:** 16
- **Mode max:** 32

**Capacity verdict:** `fits`

## Substory clusters

### S1 — Four reproducible ecotypes stratify Crohn's disease

**Punchline:** Four reproducible microbiome ecotypes stratify Crohn's disease into biologically distinct patient groups

**Critical analyses covered:**

- A1: Four reproducible IBD ecotypes — REPORT §Finding 1
- A2: UC Davis spans three ecotypes — REPORT §Finding 2

**Budget:** 4 content slides + 1 divider

**Headline slot:** A1 — 8,489-sample K=4 consensus (the section's scale claim; strongest available)

**Transition in:** (deck opener — no prior section)

**Transition out:** Close on — the ecotypes are a framework, not bit-reproducible; do the targets inside each ecotype replicate?

**Scoped figures:** fig_01, fig_03

**Cluster rationale:** These analyses jointly establish the stratification premise.

---

### S2 — Confound-free analysis yields six pathobiont targets

**Punchline:** Within-ecotype meta-analysis surfaces six actionable pathobionts that replicate at 88% on a held-out cohort

**Critical analyses covered:**

- A4: Six actionable Tier-A pathobionts — REPORT §Finding 5c

**Budget:** 4 content slides + 1 divider

**Headline slot:** A5 — 88.2% sign concordance on held-out HMP2 (the deck's strongest replicated claim; ci_present=yes)

**Transition in:** S1 closed on whether per-ecotype targets replicate — open by answering it with a confound-free meta-analysis.

**Transition out:** Close on — six targets identified and E1 replicated; can phage actually hit them?

**Scoped figures:** (none)

**Cluster rationale:** Stratification makes confound-free target discovery possible.

---

### S3 — A hybrid phage-cocktail framework

**Punchline:** A hybrid three-strategy framework turns six targets into concrete per-patient cocktail drafts

**Critical analyses covered:**

- A8: 5-phage AIEC cocktail — REPORT §Pillar 4

**Budget:** 5 content slides + 1 divider

**Headline slot:** A8 — 94.7% strain coverage (the cocktail-construction headline; effect_size_present=yes)

**Transition in:** S2 closed on whether phage can hit the targets — open with the 3-layer phage-evidence stack.

**Transition out:** (deck close — no hand-off)

**Scoped figures:** fig_11

**Cluster rationale:** Targets make intervention design possible.
"""


def _write(tmp_path: Path, content: str = FIXTURE) -> Path:
    p = tmp_path / "02_substories.md"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# deck-level fields
# ---------------------------------------------------------------------------

def test_extract_register():
    assert pdo.extract_deck_field(FIXTURE, "Register").startswith(
        "STRONG tier"
    )


def test_extract_arc():
    arc = pdo.extract_deck_field(FIXTURE, "Arc")
    assert arc.startswith("Framework → targets → intervention")


def test_extract_image_budget():
    ib = pdo.extract_deck_field(FIXTURE, "Image budget")
    assert ib.startswith("≤2 AI concept illustrations")


def test_deck_field_missing_returns_none():
    stripped = FIXTURE.replace(
        "**Register:** STRONG tier — assertive, quantitative; "
        "partial-evidence claims hedged on-slide.\n",
        "",
    )
    assert pdo.extract_deck_field(stripped, "Register") is None


# ---------------------------------------------------------------------------
# per-section fields
# ---------------------------------------------------------------------------

def test_extract_budgets():
    pairs = pdo.extract_section_field(FIXTURE, "Budget")
    assert [sid for sid, _ in pairs] == ["S1", "S2", "S3"]
    assert pairs[0][1] == "4 content slides + 1 divider"
    assert pairs[2][1] == "5 content slides + 1 divider"


def test_extract_headline_slots():
    pairs = pdo.extract_section_field(FIXTURE, "Headline slot")
    by = dict(pairs)
    assert by["S1"].startswith("A1 —")
    assert by["S2"].startswith("A5 —")
    assert by["S3"].startswith("A8 —")


def test_extract_transitions_in():
    by = dict(pdo.extract_section_field(FIXTURE, "Transition in"))
    assert by["S1"] == "(deck opener — no prior section)"
    assert by["S2"].startswith("S1 closed on")


def test_extract_transitions_out():
    by = dict(pdo.extract_section_field(FIXTURE, "Transition out"))
    assert by["S3"] == "(deck close — no hand-off)"
    assert by["S1"].startswith("Close on")


def test_extract_scoped_figures():
    by = dict(pdo.extract_section_field(FIXTURE, "Scoped figures"))
    assert by["S1"] == "fig_01, fig_03"
    assert by["S2"] == "(none)"
    assert by["S3"] == "fig_11"


def test_section_missing_field_yields_empty():
    """A section that omits a per-section field yields value '' — the
    other sections still parse."""
    stripped = FIXTURE.replace(
        "**Budget:** 4 content slides + 1 divider\n\n"
        "**Headline slot:** A5", "**Headline slot:** A5", 1,
    )
    by = dict(pdo.extract_section_field(stripped, "Budget"))
    assert by["S2"] == ""          # S2's Budget line was removed
    assert by["S1"] == "4 content slides + 1 divider"   # S1 untouched
    assert by["S3"] == "5 content slides + 1 divider"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_main_deck_field_cli(tmp_path, capsys):
    p = _write(tmp_path)
    rc = pdo.main(["--path", str(p), "--field", "register"])
    assert rc == 0
    assert "STRONG tier" in capsys.readouterr().out


def test_main_per_section_cli(tmp_path, capsys):
    p = _write(tmp_path)
    rc = pdo.main(["--path", str(p), "--field", "headline_slots"])
    assert rc == 0
    lines = capsys.readouterr().out.strip().split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("S1\tA1 —")


def test_main_file_missing_exit_1(tmp_path):
    rc = pdo.main(["--path", str(tmp_path / "nope.md"), "--field", "arc"])
    assert rc == 1


def test_main_unparseable_deck_field_exit_2(tmp_path):
    stripped = FIXTURE.replace(
        "**Arc:** Framework → targets → intervention: ecotypes make "
        "stratification possible, stratification makes confound-free "
        "targets possible.\n",
        "",
    )
    p = _write(tmp_path, stripped)
    rc = pdo.main(["--path", str(p), "--field", "arc"])
    assert rc == 2


# ---------------------------------------------------------------------------
# backward compat — parse_substories.py still parses the enriched file
# ---------------------------------------------------------------------------

def test_backward_compat_parse_substories_still_works():
    """The enriched 02_substories.md must remain fully parseable by the
    untouched parse_substories.py — its skeleton fields are intact."""
    assert ps.extract_capacity_verdict(FIXTURE) == "fits"
    assert ps.extract_substory_ids(FIXTURE) == ["S1", "S2", "S3"]
    punchlines = ps.extract_substory_punchlines(FIXTURE)
    assert [sid for sid, _ in punchlines] == ["S1", "S2", "S3"]
    assert punchlines[0][1].startswith("Four reproducible microbiome ecotypes")
