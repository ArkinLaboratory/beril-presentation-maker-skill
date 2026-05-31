"""Unit tests for v0.7 Tier C.3 — deck_close composer + orchestrator
stage + merger splice wiring (D-086).

Coverage:

1. Composer agent (prompts/deck_close.v1.md): exists on disk, self-
   identifies, pins the D-086 verbatim contract + the 4 required
   content fields.
2. Orchestrator stage_deck_close: source-level pins on:
   - mode-gating (only fires on talk-30 STRONG per Adam DQ2)
   - signal-presence check before invoking the composer
   - empty-fragment emission when no_signal_fallback
   - --resume-from accepts "deck_close"
   - should_run ordinals table includes deck_close after qa_prep
3. Merger splice (merge_compose_fragments.py):
   - --deck-close-fragment-path argument accepted
   - splices the deck_close slide between substory slides and
     cross_tenant (position rule per D-086)
   - missing fragment file → silent no-op (mode-gated upstream)
   - empty slides[] → no slide spliced (no_signal_fallback case)
   - speaker_notes_seed → speaker_notes promotion
   - works end-to-end with hand-built fragment + validates clean
4. End-to-end: orchestrator passes fragment path to merger
   (presentation_maker.sh wiring pin).
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill")
PROMPTS_DIR = SKILL_DIR / "prompts"
TOOLS_DIR = SKILL_DIR / "tools"
ORCH_SH = TOOLS_DIR / "presentation_maker.sh"
DECK_CLOSE_PROMPT = PROMPTS_DIR / "deck_close.v1.md"
MERGER_PY = TOOLS_DIR / "merge_compose_fragments.py"


# Import slide_spec for validation.
import importlib.util

_slide_spec_path = TOOLS_DIR / "slide_spec.py"
_spec = importlib.util.spec_from_file_location("slide_spec", _slide_spec_path)
assert _spec is not None and _spec.loader is not None
slide_spec = importlib.util.module_from_spec(_spec)
sys.modules["slide_spec"] = slide_spec
_spec.loader.exec_module(slide_spec)


# ---------------------------------------------------------------------------
# Composer agent (deck_close.v1.md)
# ---------------------------------------------------------------------------

def test_deck_close_v1_prompt_exists():
    """The composer agent ships with the skill."""
    assert DECK_CLOSE_PROMPT.is_file(), (
        f"deck_close composer agent missing at {DECK_CLOSE_PROMPT}")


def test_deck_close_v1_prompt_cites_d086():
    """Composer agent must cite D-086 (the decision it implements)."""
    body = DECK_CLOSE_PROMPT.read_text(encoding="utf-8")
    assert "D-086" in body, "composer agent should cite D-086"


def test_deck_close_v1_prompt_names_four_required_fields():
    """The composer must name unified_point, key_takeaways,
    forward_call, data_source — the D-086 content schema."""
    body = DECK_CLOSE_PROMPT.read_text(encoding="utf-8")
    for field in ("unified_point", "key_takeaways", "forward_call",
                  "data_source"):
        assert field in body, (
            f"composer agent missing required content field {field!r}")


def test_deck_close_v1_prompt_enforces_verbatim_contract():
    """D-086 mandates verbatim transcription, not synthesis. The
    composer must clearly say 'verbatim' so synthesis drift is
    discouraged."""
    body = DECK_CLOSE_PROMPT.read_text(encoding="utf-8").lower()
    assert "verbatim" in body, (
        "composer agent must enforce the D-086 verbatim contract")
    # Anti-pattern naming the failure mode
    assert "synthesis drift" in body or "synthesis-drift" in body, (
        "composer agent should name 'synthesis drift' as an "
        "anti-pattern so the failure mode is explicit")


def test_deck_close_v1_prompt_documents_no_signal_fallback():
    """When extract_deck_close emits no_signal_fallback=true, the
    composer must NOT author a slide; emit empty slides[]."""
    body = DECK_CLOSE_PROMPT.read_text(encoding="utf-8")
    assert "no_signal_fallback" in body
    assert "empty" in body.lower(), (
        "composer agent should document the empty-slides fallback")


def test_deck_close_v1_prompt_declares_fragment_kind():
    """Fragment envelope kind must be deck_close_set (parallel to
    cross_tenant_set + qa_anticipated_set patterns)."""
    body = DECK_CLOSE_PROMPT.read_text(encoding="utf-8")
    assert "deck_close_set" in body


# ---------------------------------------------------------------------------
# Orchestrator stage_deck_close (source-level pins)
# ---------------------------------------------------------------------------

def _extract_function(text: str, fname: str) -> str:
    """Pull a bash function body out of the orchestrator source.

    Handles heredocs whose closing JSON `}` lands at column 0
    (which would confuse a naive `find("\\n}\\n")` and truncate
    the body mid-heredoc). Tracks heredoc state explicitly so the
    column-0 `}` that closes the function is the only match used."""
    start = text.find(f"{fname}() {{")
    if start < 0:
        raise AssertionError(f"could not locate function {fname}")
    lines = text[start:].splitlines(keepends=True)
    out_lines = [lines[0]]
    in_heredoc = False
    for line in lines[1:]:
        out_lines.append(line)
        if not in_heredoc:
            if "<<EOF" in line:
                in_heredoc = True
            elif line.rstrip("\n") == "}":
                break
        else:
            if line.rstrip("\n") == "EOF":
                in_heredoc = False
    return "".join(out_lines)


def test_stage_deck_close_function_defined():
    """stage_deck_close() is defined in the orchestrator."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert "stage_deck_close() {" in text, (
        "orchestrator must define stage_deck_close()")


def test_stage_deck_close_mode_gates_to_talk_30():
    """Adam Tier-0 DQ2: deck_close is required only on talk-30
    STRONG; sub-STRONG modes skip silently. The stage must gate on
    MODE explicitly."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_function(text, "stage_deck_close")
    # Mode gate (early-return when not talk-30)
    assert '"$MODE" != "talk-30"' in body, (
        "stage_deck_close must gate on MODE != talk-30 (Adam DQ2)")
    # Must return 0 (silent skip, not failure) on the skip path
    assert "return 0" in body


def test_stage_deck_close_runs_extract_deck_close_first():
    """Stage (a): invoke extract_deck_close.py before the composer."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_function(text, "stage_deck_close")
    assert "extract_deck_close.py" in body, (
        "stage_deck_close must invoke extract_deck_close.py")
    # Extraction must precede the composer invocation
    extract_pos = body.find("extract_deck_close.py")
    compose_pos = body.find("deck_close.v1.md")
    assert extract_pos > 0 and compose_pos > 0
    assert extract_pos < compose_pos, (
        "extractor must run BEFORE composer (signal-then-compose)")


def test_stage_deck_close_checks_no_signal_fallback():
    """When extract_deck_close emits no_signal_fallback=true, the
    composer is skipped and an empty fragment is written so the
    merger doesn't try to splice a non-existent file."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_function(text, "stage_deck_close")
    assert "no_signal_fallback" in body, (
        "stage_deck_close must check no_signal_fallback before "
        "invoking the composer")
    # Empty-fragment write
    assert "deck_close_set" in body, (
        "stage_deck_close must emit an empty deck_close_set "
        "fragment on the no-signal path")


def test_stage_deck_close_invokes_composer_with_signal_path():
    """When signal is present, the composer is invoked with the
    signal path in the user prompt."""
    text = ORCH_SH.read_text(encoding="utf-8")
    body = _extract_function(text, "stage_deck_close")
    # The user-prompt must pass SIGNAL_PATH so the composer knows
    # which signal file to read.
    assert "SIGNAL_PATH" in body
    # The composer agent path is referenced
    assert "deck_close.v1.md" in body


def test_resume_from_accepts_deck_close():
    """`--resume-from deck_close` must be a valid stage name (so
    operators can resume after the extractor + composer wrote the
    fragment but the merge step failed for an unrelated reason)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Find the validation case
    case_start = text.find('case "$RESUME_FROM" in')
    assert case_start > 0
    case_end = text.find("esac", case_start)
    case_block = text[case_start:case_end]
    assert "deck_close" in case_block, (
        "RESUME_FROM validation case must include deck_close as a "
        "valid stage name")


def test_should_run_ordinals_include_deck_close_after_qa_prep():
    """The should_run ordinals table must include deck_close, and
    it must come AFTER qa_prep (substory C-slots must exist + qa
    has wrapped before the closer extracts)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Locate the should_run function body
    body = _extract_function(text, "should_run")
    assert "deck_close:" in body, (
        "should_run ordinals must include deck_close")
    # Both ordinal strings (v0_4 + default) must place deck_close
    # immediately after qa_prep (a hard pin so a future reorder
    # surfaces in tests rather than silently breaking the chain).
    for line in body.splitlines():
        if "deck_close:" in line and "ordinals=" in line:
            # Pin: qa_prep:N immediately followed by deck_close:N+1
            import re
            m = re.search(r"qa_prep:(\d+) deck_close:(\d+)", line)
            assert m, (
                f"qa_prep + deck_close must be adjacent in the "
                f"ordinals string; got: {line}")
            qa_n, dc_n = int(m.group(1)), int(m.group(2))
            assert dc_n == qa_n + 1, (
                f"deck_close ordinal must be qa_prep+1; got "
                f"qa_prep={qa_n}, deck_close={dc_n}")


def test_main_flow_invokes_stage_deck_close_after_qa_prep():
    """The main pipeline chain must call stage_deck_close after
    stage_qa_prep so substory C-slots + REPORT.md exist on disk
    when the extractor runs."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Find the should_run blocks; deck_close must come AFTER qa_prep
    qa_run = text.find("should_run qa_prep;")
    dc_run = text.find("should_run deck_close;")
    sn_run = text.find("should_run speaker_notes;")
    assert qa_run > 0 and dc_run > 0, (
        "main flow must invoke both qa_prep and deck_close stages")
    assert qa_run < dc_run, (
        "stage_deck_close must be invoked AFTER stage_qa_prep "
        "(substory C-slot conclusions must exist on disk)")
    # And before speaker_notes (which runs on substory slides only;
    # deck_close fragment is deck-level + bypasses speaker_notes
    # stage, but the ordering pin catches accidental reorderings)
    if sn_run > 0:
        assert dc_run < sn_run, (
            "stage_deck_close should run before speaker_notes so "
            "the merger sees both fragments in the same pass")


def test_orchestrator_passes_fragment_path_to_merger():
    """The merger invocation must include
    --deck-close-fragment-path so the merger picks up the fragment
    stage_deck_close wrote."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert "--deck-close-fragment-path" in text, (
        "merge_compose_fragments invocation must pass "
        "--deck-close-fragment-path so the deck_close fragment "
        "is spliced into the merged spec")


# ---------------------------------------------------------------------------
# Merger splice logic (subprocess: merge_compose_fragments.py)
# ---------------------------------------------------------------------------

# Minimal fixtures shared with the existing merger tests' shape.
_THROUGHLINE_MD = """<!-- chosen: TL1 -->
<!-- punchline: Test deck unified takeaway. -->

# Throughline (chosen: TL1)

## Candidate TL1: Test deck unified takeaway.

**Evidence map:** placeholder.
"""

_SUBSTORY_FIXTURE_S1_S2 = """# Substory clusters

### S1 — first cluster

**Question:** What does S1 ask?

**Conclusion for next substory:** S1 established the first thing.

**Punchline:** First punchline.

**Critical analyses covered:**

- A1: x — REPORT §A / NB01_one.ipynb

### S2 — second cluster

**Transition from prior:** S1 established the first thing. S2 asks the next.

**Question:** What does S2 ask?

**Punchline:** Second punchline.

**Critical analyses covered:**

- A2: y — REPORT §B / NB02_two.ipynb
"""


def _make_substory_fragment(sid: str) -> dict:
    """Minimal valid compose-fragment.v2 for one substory."""
    return {
        "schema_version": "compose-fragment.v2",
        "kind": "substory_slides",
        "substory_id": sid,
        "slides": [
            {"position": 0, "layout": "section_divider",
             "content": {"punchline": f"{sid} punchline."}},
            {"position": 1, "layout": "claim_evidence",
             "content": {"title": f"{sid} claim.",
                         "bullets": ["evidence A.", "evidence B."]}},
        ],
    }


def _make_deck_close_fragment(empty: bool = False) -> dict:
    """A canonical deck_close fragment (or empty when empty=True)."""
    if empty:
        return {
            "schema_version": "compose-fragment.v1",
            "kind": "deck_close_set",
            "mode": "talk-30",
            "tier": "STRONG",
            "slides": [],
        }
    return {
        "schema_version": "compose-fragment.v1",
        "kind": "deck_close_set",
        "mode": "talk-30",
        "tier": "STRONG",
        "slides": [
            {
                "position": 0,
                "layout": "deck_close",
                "content": {
                    "unified_point": "The deck's overall takeaway.",
                    "key_takeaways": [
                        "First arc takeaway.",
                        "Second arc takeaway.",
                        "Third arc takeaway.",
                    ],
                    "forward_call": "Next experiment / open question.",
                    "data_source": "S1 C-slot + S2 C-slot + REPORT §X.",
                },
                "speaker_notes_seed": (
                    "Speaker note expanding the forward_call."
                ),
            },
        ],
    }


def _run_merger(outdir: Path, deck_close_path: Path | None = None,
                project_id: str = "test_project",
                mode: str = "talk-30") -> subprocess.CompletedProcess:
    """Invoke merge_compose_fragments.py via subprocess. Returns the
    process result. The caller checks rc + reads the output spec."""
    throughline_path = outdir / "00_throughline.md"
    throughline_path.write_text(_THROUGHLINE_MD, encoding="utf-8")
    substory_path = outdir / "02_substories.md"
    substory_path.write_text(_SUBSTORY_FIXTURE_S1_S2, encoding="utf-8")
    (outdir / "03_slides").mkdir(exist_ok=True)
    (outdir / "03_slides" / "S1_slides.json").write_text(
        json.dumps(_make_substory_fragment("S1")), encoding="utf-8")
    (outdir / "03_slides" / "S2_slides.json").write_text(
        json.dumps(_make_substory_fragment("S2")), encoding="utf-8")
    out_spec = outdir / "slide_spec.json"
    cmd = [
        sys.executable, str(MERGER_PY),
        "--outdir", str(outdir),
        "--project-id", project_id,
        "--mode", mode,
        "--tier", "STRONG",
        "--audience", "peer",
        "--throughline-path", str(throughline_path),
        "--substory-path", str(substory_path),
        "--fragments-dir", str(outdir / "03_slides"),
        "--out", str(out_spec),
    ]
    if deck_close_path is not None:
        cmd.extend(["--deck-close-fragment-path", str(deck_close_path)])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def test_merger_accepts_deck_close_fragment_path_arg(tmp_path):
    """The --deck-close-fragment-path argument is documented in
    --help and accepted at invocation time."""
    result = subprocess.run(
        [sys.executable, str(MERGER_PY), "--help"],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert "--deck-close-fragment-path" in result.stdout
    # D-086 attribution in --help so operators know the why
    assert "D-086" in result.stdout or "deck_close" in result.stdout


def test_merger_splices_deck_close_between_substories_and_cross_tenant(tmp_path):
    """Per D-086 position rule: deck_close lands between final
    substory slide and cross_tenant / qa / acks / refs metadata
    block. With no cross_tenant or qa, deck_close → before
    acknowledgments."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    (outdir / "03_slides").mkdir()
    dc_path.write_text(json.dumps(_make_deck_close_fragment()),
                       encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    # Find the deck_close slide position
    layouts = [s["layout"] for s in spec["slides"]]
    dc_idx = layouts.index("deck_close")
    # Substory slides (last is S2's claim_evidence) come before
    # The acks/refs metadata block comes after
    # The slide ordering should be:
    #  title -> S1 divider -> S1 claim -> S2 divider -> S2 claim
    #  -> deck_close -> acknowledgments -> references
    # So deck_close index = 5; acks = 6; refs = 7
    # Verify deck_close lands AFTER the last substory slide
    assert dc_idx > 0
    assert spec["slides"][dc_idx - 1]["substory_id"] == "S2", (
        f"deck_close should immediately follow last substory slide; "
        f"got layout={spec['slides'][dc_idx - 1]['layout']} "
        f"substory_id={spec['slides'][dc_idx - 1].get('substory_id')}")
    # Verify deck_close lands BEFORE acknowledgments + references
    later_layouts = layouts[dc_idx + 1:]
    assert "acknowledgments" in later_layouts
    assert "references" in later_layouts


def test_merger_deck_close_content_preserved_verbatim(tmp_path):
    """The deck_close fragment's content fields are written to the
    merged spec verbatim (no merger-side rewriting)."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(_make_deck_close_fragment()),
                       encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    dc_slide = next(s for s in spec["slides"] if s["layout"] == "deck_close")
    content = dc_slide["content"]
    assert content["unified_point"] == "The deck's overall takeaway."
    assert content["key_takeaways"] == [
        "First arc takeaway.",
        "Second arc takeaway.",
        "Third arc takeaway.",
    ]
    assert content["forward_call"] == "Next experiment / open question."
    assert content["data_source"] == "S1 C-slot + S2 C-slot + REPORT §X."


def test_merger_promotes_speaker_notes_seed_to_speaker_notes(tmp_path):
    """speaker_notes_seed → speaker_notes promotion (parallel to
    cross_tenant's pattern; the speaker_notes stage runs only on
    substory slides, so deck-level slides need direct promotion).

    v0.8/D-094: speaker_notes now also includes a **Sources:**
    appendix appended from content.data_source. The seed text
    appears first; the Sources appendix follows after a blank line.
    """
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(_make_deck_close_fragment()),
                       encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    dc_slide = next(s for s in spec["slides"] if s["layout"] == "deck_close")
    # v0.8/D-094 shape: seed body + blank line + **Sources:** appendix
    notes = dc_slide["speaker_notes"]
    assert notes.startswith("Speaker note expanding the forward_call."), (
        f"speaker_notes must start with the seed body verbatim; got: "
        f"{notes!r}")
    assert "**Sources:** S1 C-slot + S2 C-slot + REPORT §X." in notes, (
        f"v0.8/D-094: speaker_notes must contain the **Sources:** "
        f"appendix derived from content.data_source; got: {notes!r}")
    # speaker_notes_seed should be stripped
    assert "speaker_notes_seed" not in dc_slide
    # content.data_source preserved (schema-stable per D-094)
    assert dc_slide["content"]["data_source"] == \
        "S1 C-slot + S2 C-slot + REPORT §X."


def test_merger_splices_no_slide_on_empty_fragment(tmp_path):
    """no_signal_fallback case: fragment has empty slides[]; merger
    splices nothing (no deck_close in the merged spec)."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(_make_deck_close_fragment(empty=True)),
                       encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    layouts = [s["layout"] for s in spec["slides"]]
    assert "deck_close" not in layouts, (
        "empty deck_close fragment must produce no deck_close slide")


def test_merger_silent_when_fragment_missing(tmp_path):
    """Missing fragment file (path passed but file absent) → silent
    no-op (mode-gated upstream; not the merger's job to enforce
    presence)."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    # Path passed but no file written
    dc_path = outdir / "03_slides" / "deck_close.json"
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    layouts = [s["layout"] for s in spec["slides"]]
    assert "deck_close" not in layouts


def test_merger_silent_when_no_fragment_path_arg(tmp_path):
    """No --deck-close-fragment-path arg → no splice (back-compat
    with pre-Tier-C.3 merger invocations)."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    result = _run_merger(outdir, deck_close_path=None)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    layouts = [s["layout"] for s in spec["slides"]]
    assert "deck_close" not in layouts


def test_merger_deck_close_spec_validates(tmp_path):
    """End-to-end: merger output with deck_close splice validates
    against the slide_spec contract (Tier C.0 schema)."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(_make_deck_close_fragment()),
                       encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    issues = slide_spec.validate_slide_spec(spec)
    assert issues == [], (
        "merged spec with deck_close must validate; got:\n  "
        + "\n  ".join(i.format() for i in issues)
    )


def test_merger_position_field_continues_through_deck_close(tmp_path):
    """The 1-based position field continues monotonically through
    the deck_close slide (so the revise loop's add_slide path
    can do surgical insertion)."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(_make_deck_close_fragment()),
                       encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    for idx, s in enumerate(spec["slides"], start=1):
        assert s.get("position") == idx, (
            f"slide at idx {idx} (layout={s.get('layout')}) "
            f"has position={s.get('position')!r}; expected {idx}")


# ===========================================================================
# v0.8 Tier B — data_source → speaker_notes promotion (D-094)
# ===========================================================================
#
# v0.7 Tier-I finding 3 (fdm slide-32 "directions leak"): the
# deck_close renderer drew content.data_source as a font-10 footer
# band on the slide face, exposing internal scaffolding ("C-slot",
# "REPORT.md §X") to the audience.
#
# D-094 fix: the merger promotes data_source into speaker_notes as a
# **Sources:** appendix (appended after any speaker_notes_seed body).
# The renderer no longer draws data_source on the slide face; schema
# preserved per D-086.
#
# These tests pin the data_source promotion shape so a future merger
# refactor that drops the appendix breaks a test, not the audit-trail
# contract.


def _make_deck_close_fragment_no_seed():
    """deck_close fragment with content.data_source but NO
    speaker_notes_seed. Tests that the merger still emits **Sources:**
    notes when only data_source is present."""
    return {
        "schema_version": "compose-fragment.v1",
        "kind": "deck_close_set",
        "mode": "talk-30",
        "tier": "STRONG",
        "slides": [
            {
                "position": 0,
                "layout": "deck_close",
                "content": {
                    "unified_point": "Overall takeaway.",
                    "key_takeaways": [
                        "Arc 1 takeaway.",
                        "Arc 2 takeaway.",
                        "Arc 3 takeaway.",
                    ],
                    "forward_call": "Next step.",
                    "data_source": "S1 C-slot + REPORT §Y.",
                },
                # No speaker_notes_seed field at all
            },
        ],
    }


def _make_deck_close_fragment_empty_data_source():
    """deck_close fragment with seed but empty data_source.
    Edge case: validator may not have run yet (cascade is advisory);
    merger should produce notes from the seed alone, not crash."""
    frag = _make_deck_close_fragment()
    frag["slides"][0]["content"]["data_source"] = ""
    return frag


def test_merger_d094_promotes_data_source_to_speaker_notes_sources_appendix(
        tmp_path):
    """When BOTH speaker_notes_seed and content.data_source are
    present, speaker_notes contains seed + blank line + **Sources:**
    appendix. Pin the exact concatenation shape."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(_make_deck_close_fragment()),
                       encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    dc_slide = next(s for s in spec["slides"] if s["layout"] == "deck_close")
    expected = (
        "Speaker note expanding the forward_call.\n\n"
        "**Sources:** S1 C-slot + S2 C-slot + REPORT §X."
    )
    assert dc_slide["speaker_notes"] == expected, (
        f"v0.8/D-094: speaker_notes must be 'seed\\n\\n**Sources:** "
        f"<data_source>'; got: {dc_slide['speaker_notes']!r}")


def test_merger_d094_promotes_data_source_only_when_seed_missing(tmp_path):
    """When speaker_notes_seed is absent but content.data_source is
    present, speaker_notes = '**Sources:** <data_source>' alone
    (no leading blank line, no orphan content)."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(_make_deck_close_fragment_no_seed()),
                       encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    dc_slide = next(s for s in spec["slides"] if s["layout"] == "deck_close")
    assert dc_slide["speaker_notes"] == "**Sources:** S1 C-slot + REPORT §Y.", (
        f"v0.8/D-094: with no seed but a data_source, speaker_notes "
        f"must be the Sources appendix alone; got: "
        f"{dc_slide['speaker_notes']!r}")


def test_merger_d094_keeps_seed_only_when_data_source_empty(tmp_path):
    """Edge case: validator hasn't enforced data_source yet (cascade
    is advisory). Empty data_source → speaker_notes is the seed
    alone, no orphan **Sources:** line."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(_make_deck_close_fragment_empty_data_source()),
                       encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    dc_slide = next(s for s in spec["slides"] if s["layout"] == "deck_close")
    assert dc_slide["speaker_notes"] == (
        "Speaker note expanding the forward_call."), (
        f"empty data_source must NOT emit an orphan **Sources:** line; "
        f"got: {dc_slide['speaker_notes']!r}")
    assert "Sources" not in dc_slide["speaker_notes"]


def test_merger_d094_data_source_preserved_in_content(tmp_path):
    """Schema-stable per D-094: content.data_source remains present on
    the merged slide for audit-trail consumers (validator,
    cascade reader, downstream tools). The promotion is ADDITIVE to
    speaker_notes; it doesn't strip data_source from content."""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(_make_deck_close_fragment()),
                       encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    dc_slide = next(s for s in spec["slides"] if s["layout"] == "deck_close")
    # content.data_source preserved verbatim
    assert dc_slide["content"]["data_source"] == \
        "S1 C-slot + S2 C-slot + REPORT §X.", (
        "D-094 promotion must NOT remove data_source from content; "
        "schema preserved per D-086.")


def test_merger_d094_no_speaker_notes_when_both_missing(tmp_path):
    """If both speaker_notes_seed AND data_source are absent/empty,
    no speaker_notes field is created. Defensive: keeps the schema
    minimal when there's nothing to promote."""
    frag = _make_deck_close_fragment_no_seed()
    frag["slides"][0]["content"]["data_source"] = ""
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(frag), encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    dc_slide = next(s for s in spec["slides"] if s["layout"] == "deck_close")
    assert "speaker_notes" not in dc_slide or not dc_slide["speaker_notes"], (
        "no seed and no data_source → no speaker_notes; got: "
        f"{dc_slide.get('speaker_notes')!r}")


def test_merger_d094_does_not_overwrite_existing_speaker_notes(tmp_path):
    """If the fragment already provides a full speaker_notes field
    (rare; the v1 contract uses speaker_notes_seed instead), the
    merger must NOT clobber it with seed+data_source. The
    'speaker_notes not in cleaned' guard preserves authored notes."""
    frag = _make_deck_close_fragment()
    # Composer authored speaker_notes directly (unusual; the v1
    # contract prefers speaker_notes_seed, but the merger must be
    # defensive against this shape).
    frag["slides"][0]["speaker_notes"] = "AUTHORED-NOTES-WIN"
    outdir = tmp_path / "draft_1"
    outdir.mkdir()
    (outdir / "03_slides").mkdir()
    dc_path = outdir / "03_slides" / "deck_close.json"
    dc_path.write_text(json.dumps(frag), encoding="utf-8")
    result = _run_merger(outdir, deck_close_path=dc_path)
    assert result.returncode == 0, result.stderr
    spec = json.loads((outdir / "slide_spec.json").read_text(encoding="utf-8"))
    dc_slide = next(s for s in spec["slides"] if s["layout"] == "deck_close")
    assert dc_slide["speaker_notes"] == "AUTHORED-NOTES-WIN", (
        "explicit speaker_notes must NOT be overwritten by the "
        "seed→notes + data_source promotion")
