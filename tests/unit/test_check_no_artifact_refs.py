"""Tests for check_no_artifact_refs.py — process-detail-bleed post-checker.

v0.3.8 mechanical post-checker that flags internal-artifact references on
slides (notebook IDs, file paths, REPORT.md sections, analysis-layer
codes). Surfaced by the 2026-05-06 ibd_phage_targeting talk-45 review
where ~11 of 37 slides leaked these patterns.

Test coverage:
- pattern matching: each ArtifactPattern catches its target shapes and
  doesn't catch obviously-clean prose
- whitelist: TL\\d / S\\d (substory + throughline IDs) are NOT flagged by
  the analysis-layer-code pattern (they're legitimate project structure)
- slide traversal: text fields, list fields, dict-list fields (bullets),
  and speaker_notes are all scanned with correct location labels
- top-level run: scan_slide_spec aggregates correctly; report counters
  and hits_by_pattern populate
- exit codes: --strict mode returns 1 on hits; default returns 0
- output: .md and .json land in audit/; --json-only skips .md
- error paths: missing draft_dir, missing slide_spec.json, malformed JSON
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2]
        / "src" / "beril_presentation_maker" / "skill" / "tools")
)

import check_no_artifact_refs as cnr  # noqa: E402


# ---------------------------------------------------------------------------
# Pattern unit tests — each ArtifactPattern's regex against positive +
# negative examples
# ---------------------------------------------------------------------------

def _patterns_by_name():
    return {p.name: p for p in cnr._PATTERNS}


class TestNotebookIdPattern:
    pattern = _patterns_by_name()["notebook-id"]

    @pytest.mark.parametrize("text,match", [
        ("NB01", "NB01"),
        ("NB04", "NB04"),
        ("NB04b", "NB04b"),
        ("NB04c-e", "NB04c-e"),
        ("NB07 v1.8", "NB07 v1.8"),
        ("NB07 v1", "NB07 v1"),
        ("see NB12 phage availability", "NB12"),
        ("NB04g", "NB04g"),
    ])
    def test_matches_notebook_ids(self, text, match):
        m = self.pattern.regex.search(text)
        assert m is not None, f"expected match for {text!r}"
        assert m.group(0) == match

    @pytest.mark.parametrize("text", [
        "MNBK is fine",            # NB embedded in larger word
        "TLB is unrelated",        # T-L-B different shape
        "ABC123 is not a notebook",  # ABC prefix
    ])
    def test_does_not_match_non_notebooks(self, text):
        assert self.pattern.regex.search(text) is None


class TestNotebookFilePattern:
    pattern = _patterns_by_name()["notebook-file"]

    @pytest.mark.parametrize("text,match", [
        ("NB04h_hmp2_external_replication.ipynb", "NB04h_hmp2_external_replication.ipynb"),
        ("see NB12.ipynb", "NB12.ipynb"),
        ("NB07-v18.ipynb", "NB07-v18.ipynb"),
    ])
    def test_matches_notebook_files(self, text, match):
        m = self.pattern.regex.search(text)
        assert m is not None
        assert m.group(0) == match

    def test_does_not_match_other_ipynb(self):
        assert self.pattern.regex.search("plain.ipynb") is None
        assert self.pattern.regex.search("scratch.ipynb") is None


class TestDataPathPattern:
    pattern = _patterns_by_name()["data-tsv-path"]

    @pytest.mark.parametrize("text", [
        "data/nb09b_theme_replication.tsv",
        "data/nb05_tier_a_scored.tsv",
        "data/sub/path.csv",
        "see data/results.json",
        "data/nb01.parquet",
    ])
    def test_matches_data_paths(self, text):
        assert self.pattern.regex.search(text) is not None

    @pytest.mark.parametrize("text", [
        "metadata is fine",
        "the data showed",
        "results.tsv without the data/ prefix",
    ])
    def test_does_not_match_non_data_paths(self, text):
        assert self.pattern.regex.search(text) is None


class TestReportMdPattern:
    pattern = _patterns_by_name()["report-md-section"]

    @pytest.mark.parametrize("text", [
        "REPORT.md",
        "REPORT.md §Pillar 2 opener #6",
        "REPORT §16 NB09b",
        "see REPORT.md for details",
    ])
    def test_matches_report_refs(self, text):
        assert self.pattern.regex.search(text) is not None

    @pytest.mark.parametrize("text", [
        "the report is fine",
        "report shows ...",
        "MyReport.md",  # not the project's REPORT.md
    ])
    def test_does_not_match_generic_report(self, text):
        assert self.pattern.regex.search(text) is None


class TestPillarSectionPattern:
    pattern = _patterns_by_name()["pillar-section"]

    @pytest.mark.parametrize("text", [
        "§Pillar 2",
        "§Pillar 3 analytic approach",
        "see §Pillar 5",
    ])
    def test_matches_pillar_refs(self, text):
        assert self.pattern.regex.search(text) is not None

    def test_does_not_match_pillar_word(self):
        assert self.pattern.regex.search("the pillar of the work") is None


class TestAnalysisLayerCodePattern:
    pattern = _patterns_by_name()["analysis-layer-code"]

    @pytest.mark.parametrize("text,match", [
        ("L13", "L13"),
        ("A16", "A16"),
        ("H3c", "H3c"),
        ("E1 pathobionts", "E1"),
        ("(L7) check", "L7"),
        ("E3 Tier-A", "E3"),
    ])
    def test_matches_layer_codes(self, text, match):
        m = self.pattern.regex.search(text)
        assert m is not None, f"expected match for {text!r}"
        assert m.group(0) == match

    @pytest.mark.parametrize("text", [
        "TL1",       # throughline ID — whitelisted
        "TL2",       # throughline ID
        "TL10",      # throughline ID
        "S1",        # substory ID — whitelisted
        "S2",        # substory ID
    ])
    def test_whitelists_substory_throughline_ids(self, text):
        m = self.pattern.regex.search(text)
        assert m is None, f"unexpected match for whitelisted {text!r}: {m}"

    @pytest.mark.parametrize("text", [
        "the L word",
        "100MB",            # no leading capital letter immediately before digit
        "abc123",
    ])
    def test_does_not_match_non_codes(self, text):
        assert self.pattern.regex.search(text) is None


# ---------------------------------------------------------------------------
# Slide-text traversal
# ---------------------------------------------------------------------------

class TestCollectSlideSpans:
    def test_text_fields_collected(self):
        slide = {
            "layout": "claim_evidence",
            "content": {
                "title": "Big claim",
                "caption": "with a caption",
                "subtitle": "subtitle here",
            },
        }
        spans = cnr._collect_slide_spans(slide)
        locs = {s.location for s in spans}
        assert locs == {"title", "caption", "subtitle"}

    def test_list_fields_collected_with_indices(self):
        slide = {
            "layout": "methods_summary",
            "content": {
                "title": "Methods",
                "bullets": ["one", "two", "three"],
            },
        }
        spans = cnr._collect_slide_spans(slide)
        locs = sorted(s.location for s in spans)
        assert locs == ["bullets[0]", "bullets[1]", "bullets[2]", "title"]

    def test_implications_dict_bullets(self):
        slide = {
            "layout": "implications",
            "content": {
                "title": "Implications",
                "bullets": [
                    {"claim": "First claim", "evidence_pointer": "S1"},
                    {"claim": "Second claim", "evidence_pointer": "S2"},
                ],
            },
        }
        spans = cnr._collect_slide_spans(slide)
        locs = sorted(s.location for s in spans)
        assert locs == [
            "bullets[0].claim", "bullets[0].evidence_pointer",
            "bullets[1].claim", "bullets[1].evidence_pointer",
            "title",
        ]

    def test_speaker_notes_collected(self):
        slide = {
            "layout": "claim_evidence",
            "content": {"title": "Claim"},
            "speaker_notes": "Long form speaker notes go here.",
        }
        spans = cnr._collect_slide_spans(slide)
        notes_span = [s for s in spans if s.location == "speaker_notes"]
        assert len(notes_span) == 1
        assert notes_span[0].text == "Long form speaker notes go here."

    def test_empty_string_fields_skipped(self):
        slide = {
            "layout": "claim_evidence",
            "content": {
                "title": "Claim",
                "caption": "",       # empty — should not produce a span
                "subtitle": None,    # missing — also skipped
            },
        }
        spans = cnr._collect_slide_spans(slide)
        locs = {s.location for s in spans}
        assert locs == {"title"}


# ---------------------------------------------------------------------------
# scan_slide
# ---------------------------------------------------------------------------

class TestScanSlide:
    def test_clean_slide_no_hits(self):
        slide = {
            "id": 1,
            "layout": "claim_evidence",
            "content": {
                "title": "Iron acquisition is the dominant CD pathobiont mechanism",
                "bullets": [
                    "Lloyd-Price 2019 (HMP2 cohort, n=1,627): "
                    "82% sign-concordance",
                    "Replicated in 3 independent cohorts",
                ],
            },
            "speaker_notes": "Standard methods caveats apply.",
        }
        hits = cnr.scan_slide(slide, slide_position=0)
        assert hits == []

    def test_artifact_laden_slide_multiple_hits(self):
        """The kind of slide ibd_phage_targeting actually shipped."""
        slide = {
            "id": 11,
            "layout": "claim_evidence",
            "content": {
                "title": "E1 pathobionts replicate in HMP2",
                "caption": (
                    "REPORT.md §Pillar 2 opener #6; "
                    "NB04h_hmp2_external_replication.ipynb"
                ),
                "bullets": [
                    "L13 sensitivity analysis confirms",
                    "data/nb05_tier_a_scored.tsv has the matrix",
                ],
            },
        }
        hits = cnr.scan_slide(slide, slide_position=10)
        assert len(hits) >= 5  # at minimum: E1, REPORT.md+§Pillar, NB04h.ipynb, L13, data/...
        patterns_seen = {h.pattern_name for h in hits}
        assert "report-md-section" in patterns_seen
        assert "pillar-section" in patterns_seen
        assert "notebook-file" in patterns_seen
        assert "data-tsv-path" in patterns_seen
        assert "analysis-layer-code" in patterns_seen
        # Each hit has slide_id + position + layout
        for h in hits:
            assert h.slide_id == 11
            assert h.slide_position == 10
            assert h.slide_layout == "claim_evidence"

    def test_hit_records_correct_location(self):
        slide = {
            "id": 5,
            "layout": "claim_evidence",
            "content": {
                "title": "Clean title",
                "bullets": ["Clean bullet 0", "L13 hit in bullet 1", "Clean bullet 2"],
            },
        }
        hits = cnr.scan_slide(slide, slide_position=4)
        assert len(hits) == 1
        assert hits[0].location == "bullets[1]"
        assert hits[0].matched_text == "L13"

    def test_speaker_notes_hits_labeled(self):
        slide = {
            "id": 3,
            "layout": "claim_evidence",
            "content": {"title": "Clean"},
            "speaker_notes": "See NB04h for details.",
        }
        hits = cnr.scan_slide(slide, slide_position=2)
        assert len(hits) >= 1
        nb_hit = [h for h in hits if h.pattern_name == "notebook-id"][0]
        assert nb_hit.location == "speaker_notes"


# ---------------------------------------------------------------------------
# scan_slide_spec aggregator
# ---------------------------------------------------------------------------

class TestScanSlideSpec:
    def test_empty_spec_zero_hits(self, tmp_path):
        spec = {"slides": []}
        report = cnr.scan_slide_spec(spec, tmp_path)
        assert report.n_slides == 0
        assert report.n_total_hits == 0
        assert report.n_slides_with_hits == 0
        assert report.hits == []
        assert report.hits_by_pattern == {}

    def test_clean_spec_zero_hits(self, tmp_path):
        spec = {
            "slides": [
                {
                    "id": i, "layout": "claim_evidence",
                    "content": {"title": f"Clean title {i}",
                                "bullets": ["Clean bullet"]},
                }
                for i in range(3)
            ],
        }
        report = cnr.scan_slide_spec(spec, tmp_path)
        assert report.n_slides == 3
        assert report.n_total_hits == 0

    def test_mixed_spec_aggregates(self, tmp_path):
        spec = {
            "slides": [
                {  # clean
                    "id": 1, "layout": "title",
                    "content": {"title": "Clean", "presenter": "Adam", "date": "2026-05-07"},
                },
                {  # has artifact references
                    "id": 2, "layout": "claim_evidence",
                    "content": {
                        "title": "REPORT.md is showing",
                        "bullets": ["L13 finding", "see NB04h"],
                    },
                },
                {  # also has artifacts
                    "id": 3, "layout": "claim_evidence",
                    "content": {
                        "title": "Clean here",
                        "caption": "data/nb05.tsv has the matrix",
                    },
                },
            ],
        }
        report = cnr.scan_slide_spec(spec, tmp_path)
        assert report.n_slides == 3
        assert report.n_slides_with_hits == 2
        assert report.n_total_hits >= 4
        # hits_by_pattern populated with multiple distinct categories
        assert len(report.hits_by_pattern) >= 3


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

class TestRenderMarkdown:
    def test_clean_report_renders_pass_message(self, tmp_path):
        report = cnr.CheckReport(draft_dir=tmp_path, n_slides=5)
        md = cnr.render_markdown(report)
        assert "✓" in md
        assert "no artifact references" in md.lower() or "0 hits" in md.lower() or "clean" in md.lower()

    def test_dirty_report_renders_per_slide_section(self, tmp_path):
        spec = {
            "slides": [
                {
                    "id": 11, "layout": "claim_evidence",
                    "content": {
                        "title": "E1 pathobionts replicate",
                        "caption": "REPORT.md §Pillar 2; NB04h.ipynb",
                    },
                },
            ],
        }
        report = cnr.scan_slide_spec(spec, tmp_path)
        md = cnr.render_markdown(report)
        assert "## Per-slide hits" in md
        assert "Slide 0" in md  # zero-indexed position
        assert "claim_evidence" in md
        assert "Recommended hand-edit pass" in md
        assert "advisory" in md.lower()


# ---------------------------------------------------------------------------
# CLI / file I/O
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_draft(tmp_path):
    """Build a minimal draft_N directory with a slide_spec.json."""
    draft = tmp_path / "draft_1"
    (draft / "working").mkdir(parents=True)
    spec = {
        "schema_version": "1.0",
        "project_id": "test_project",
        "mode": "talk-30",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {"id": "TL1", "punchline": "x", "tier_evidence": "STRONG"},
        "substories": [],
        "slides": [
            {
                "id": 1, "layout": "title",
                "content": {
                    "title": "Clean title slide",
                    "presenter": "Adam Arkin", "date": "2026-05-07",
                },
            },
            {
                "id": 2, "layout": "claim_evidence",
                "content": {
                    "title": "L13 sensitivity analysis confirms",
                    "caption": "REPORT.md §Pillar 2; NB04h.ipynb",
                    "bullets": ["data/nb05_tier_a_scored.tsv reproduced"],
                },
            },
        ],
    }
    (draft / "working" / "slide_spec.json").write_text(json.dumps(spec))
    return draft


class TestCheckArtifactRefs:
    def test_runs_against_real_layout(self, fake_draft):
        report = cnr.check_artifact_refs(fake_draft)
        assert report.n_slides == 2
        assert report.n_slides_with_hits == 1
        assert report.n_total_hits >= 4

    def test_missing_slide_spec_raises(self, tmp_path):
        (tmp_path / "working").mkdir()
        with pytest.raises(FileNotFoundError):
            cnr.check_artifact_refs(tmp_path)


class TestCLI:
    def test_clean_run_exit_0(self, tmp_path, capsys):
        draft = tmp_path / "draft_1"
        (draft / "working").mkdir(parents=True)
        spec = {
            "slides": [
                {"id": 1, "layout": "title",
                 "content": {"title": "Clean", "presenter": "X", "date": "2026-05-07"}},
            ],
        }
        (draft / "working" / "slide_spec.json").write_text(json.dumps(spec))

        rc = cnr.main([str(draft)])
        assert rc == 0
        # Audit files written
        assert (draft / "audit" / "no_artifact_refs.json").is_file()
        assert (draft / "audit" / "no_artifact_refs.md").is_file()

    def test_dirty_advisory_exit_0(self, fake_draft):
        rc = cnr.main([str(fake_draft)])
        assert rc == 0  # advisory by default

    def test_dirty_strict_exit_1(self, fake_draft):
        rc = cnr.main([str(fake_draft), "--strict"])
        assert rc == 1

    def test_json_only_skips_md(self, fake_draft):
        rc = cnr.main([str(fake_draft), "--json-only"])
        assert rc == 0
        assert (fake_draft / "audit" / "no_artifact_refs.json").is_file()
        assert not (fake_draft / "audit" / "no_artifact_refs.md").is_file()

    def test_quiet_suppresses_summary(self, fake_draft, capsys):
        rc = cnr.main([str(fake_draft), "--quiet"])
        assert rc == 0
        captured = capsys.readouterr()
        # Quiet mode: no summary on stderr
        assert "hit(s)" not in captured.err
        assert "clean" not in captured.err

    def test_missing_draft_dir_exit_2(self, tmp_path):
        rc = cnr.main([str(tmp_path / "nonexistent")])
        assert rc == 2

    def test_missing_slide_spec_exit_2(self, tmp_path):
        draft = tmp_path / "draft_1"
        draft.mkdir()
        rc = cnr.main([str(draft)])
        assert rc == 2

    def test_malformed_slide_spec_exit_2(self, tmp_path):
        draft = tmp_path / "draft_1"
        (draft / "working").mkdir(parents=True)
        (draft / "working" / "slide_spec.json").write_text("not valid json{{{")
        rc = cnr.main([str(draft)])
        assert rc == 2


# ---------------------------------------------------------------------------
# Real-data smoke (uses the uploaded ibd_phage_targeting slide_spec.json
# if available; otherwise skipped). This is the big regression test —
# ensures we catch the patterns the memoryless reviewer flagged on the
# real deck.
# ---------------------------------------------------------------------------

class TestRealIbdPhageTargetingDeck:
    """Regression test against the actual ibd_phage_targeting slide_spec
    that surfaced this whole class of bug. If the fixture is absent (e.g.,
    in CI environments without the upload), tests are skipped."""

    @pytest.fixture
    def ibd_spec_path(self):
        # The slide_spec was uploaded to the workspace at sandbox path
        candidates = [
            Path("/sessions/epic-peaceful-faraday/mnt/uploads/slide_spec.json"),
        ]
        for p in candidates:
            if p.is_file():
                return p
        pytest.skip("ibd_phage_targeting slide_spec.json fixture not available")

    def test_ibd_deck_flags_at_least_10_slides(self, ibd_spec_path, tmp_path):
        """Memoryless reviewer flagged ~11 of 37 slides with verbatim
        artifact references. Our checker should catch at least 10 of
        those slides as having hits (allowing slack for our regex
        being slightly different scope than the human reviewer's)."""
        draft = tmp_path / "draft_1"
        (draft / "working").mkdir(parents=True)
        (draft / "working" / "slide_spec.json").write_text(
            ibd_spec_path.read_text()
        )
        report = cnr.check_artifact_refs(draft)
        assert report.n_slides == 37
        assert report.n_slides_with_hits >= 10, (
            f"expected ≥10 slides flagged on ibd_phage_targeting deck; "
            f"got {report.n_slides_with_hits}"
        )

    def test_ibd_deck_catches_specific_patterns(self, ibd_spec_path, tmp_path):
        """The reviewer flagged specific patterns: notebook-id, REPORT.md,
        notebook-file, analysis-layer-code. All five should appear in
        hits_by_pattern."""
        draft = tmp_path / "draft_1"
        (draft / "working").mkdir(parents=True)
        (draft / "working" / "slide_spec.json").write_text(
            ibd_spec_path.read_text()
        )
        report = cnr.check_artifact_refs(draft)
        for expected_pattern in (
            "notebook-id", "report-md-section", "notebook-file",
            "analysis-layer-code",
        ):
            assert expected_pattern in report.hits_by_pattern, (
                f"expected {expected_pattern} pattern to fire on ibd deck; "
                f"got patterns: {sorted(report.hits_by_pattern.keys())}"
            )
