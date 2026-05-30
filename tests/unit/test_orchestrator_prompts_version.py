"""Tests for the v0.5 Tier A `--prompts-version` flag wiring.

Per D-074: orchestrator accepts `--prompts-version {v1,v2,v3}`;
default v2; dispatcher helpers route substory_design + slide_compose
stages to the version-matched prompt file. Independent axis from
`--architecture-pipeline`.

Tests exercise the shell snippet directly via `bash -c` extraction
(mirrors test_orchestrator_image_provider.py pattern). The
dispatcher helpers are bash functions; we extract them + the
PROMPTS_DIR variable + invoke them with $PROMPTS_VERSION set.
"""
from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


def _run_dispatch(prompts_version: str, prompts_dir: Path,
                  helper: str,
                  slide_compose_v3_concat_path: str = "",
                  substory_design_v3_concat_path: str = "",
                  slide_compose_v3_1_concat_path: str = "",
                  slide_compose_v3_2_concat_path: str = "",
                  ) -> tuple[int, str, str]:
    """Invoke a dispatcher helper (`_substory_design_prompt_path` or
    `_slide_compose_prompt_path`) with the given PROMPTS_VERSION + a
    synthetic PROMPTS_DIR. Returns (rc, stdout, stderr).

    The helpers are defined in the orchestrator immediately after the
    --prompts-version validation block; we extract them by their
    function-name markers.

    Per v0.5.1/D-075 the v3 dispatcher returns the value of a shell
    variable populated by `build_v3_concat_prompts` at orchestrator
    start. For unit tests we pass the desired concat path in via the
    same shell-var names so the dispatcher echoes them back.

    v0.7/D-085 adds SLIDE_COMPOSE_V3_2_CONCAT_PATH for the v3.2 stack.
    """
    text = ORCH_SH.read_text(encoding="utf-8")
    # Pull the two helper definitions.
    helpers_block_start = text.find("_substory_design_prompt_path() {")
    helpers_block_end = text.find("\n}\n", text.find(
        "_slide_compose_prompt_path() {")) + 2
    if helpers_block_start < 0 or helpers_block_end < 2:
        raise AssertionError(
            "could not extract dispatcher helpers from orchestrator")
    helpers_src = text[helpers_block_start:helpers_block_end]

    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        PROMPTS_DIR={prompts_dir!s}
        PROMPTS_VERSION={prompts_version!r}
        SLIDE_COMPOSE_V3_CONCAT_PATH={slide_compose_v3_concat_path!r}
        SUBSTORY_DESIGN_V3_CONCAT_PATH={substory_design_v3_concat_path!r}
        SLIDE_COMPOSE_V3_1_CONCAT_PATH={slide_compose_v3_1_concat_path!r}
        SLIDE_COMPOSE_V3_2_CONCAT_PATH={slide_compose_v3_2_concat_path!r}
        {helpers_src}
        {helper}
        """)
    result = subprocess.run(
        ["bash", "-c", wrapper],
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode, result.stdout.strip(), result.stderr


# ---------------------------------------------------------------------------
# Dispatcher helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version,expected_filename", [
    ("v1", "substory_design.v1.md"),
    ("v2", "substory_design.v1.md"),  # v2 reuses v1 substory_design
    # Per D-075/D-078, v3 substory_design is no longer a single file —
    # the dispatcher returns the build-time concat path. The
    # conventional filename `build_v3_concat_prompts` writes is
    # `substory_design.v3.concat.md` under audit/_prompts/.
    ("v3", "substory_design.v3.concat.md"),
    # v0.6/D-080: v3.1 reuses the v3 substory_design concat
    # (substory_design isn't changed in v3.1).
    ("v3.1", "substory_design.v3.concat.md"),
    # v0.7/D-085 Tier A: v3.2 also reuses v3 substory_design until
    # Tier B (D-087) ships the substory_design.v3.2_overlay (the
    # `transition_from_prior` field emitter). Until then, v3.2
    # invocations get the v3 substory_design concat.
    ("v3.2", "substory_design.v3.concat.md"),
])
def test_substory_design_dispatcher(version, expected_filename, tmp_path):
    """Per D-074: v1/v2 → v1 substory_design (identical contract);
    v3 → concat(v1 + v3_overlay) per D-078; v3.1 + v3.2 (Tier A) also
    point at the v3 concat (substory_design unchanged in v3.1 per
    D-080; v3.2 Tier B will extend per D-087). Per D-075/D-078 the
    v3 path comes from a build-time shell var; the test simulates
    that by setting SUBSTORY_DESIGN_V3_CONCAT_PATH to the expected
    path."""
    v3_path = (f"{tmp_path}/{expected_filename}"
               if version in ("v3", "v3.1", "v3.2") else "")
    rc, stdout, stderr = _run_dispatch(
        version, tmp_path, "_substory_design_prompt_path",
        substory_design_v3_concat_path=v3_path)
    assert rc == 0, f"helper failed: {stderr}"
    assert stdout == f"{tmp_path}/{expected_filename}"


@pytest.mark.parametrize("version,expected_filename", [
    ("v1", "slide_compose.v1.md"),
    ("v2", "slide_compose.v2.md"),
    # Per D-075 v3 is no longer a single file on disk — the dispatcher
    # returns the concat path populated at build time. The expected
    # "filename" here is the conventional name `build_v3_concat_prompts`
    # writes (`slide_compose.v3.concat.md` under audit/_prompts/).
    ("v3", "slide_compose.v3.concat.md"),
    # v0.6/D-080: v3.1 stacks the figure-utilization overlay on the
    # v3 chain. Distinct concat path so a v3 pass record doesn't
    # accidentally satisfy a v3.1 gate-check.
    ("v3.1", "slide_compose.v3.1.concat.md"),
    # v0.7/D-085: v3.2 stacks the figure-relevance refinement +
    # deck_close + arc-transition USAGE overlay on the v3.1 chain.
    # Distinct concat path (different prompt-body sha) so a v3.1
    # smoke-pass record doesn't accidentally satisfy a v3.2 gate-check.
    ("v3.2", "slide_compose.v3.2.concat.md"),
])
def test_slide_compose_dispatcher(version, expected_filename, tmp_path):
    """Per D-074: each version maps to a distinct slide_compose
    prompt. v0.5.1/D-075 + v0.6/D-080 + v0.7/D-085: the dispatcher
    echoes the version-matched shell var
    (SLIDE_COMPOSE_V3_CONCAT_PATH / V3_1 / V3_2) populated at
    orchestrator start by build_v3_concat_prompts. The test
    simulates this by passing the synthetic concat paths through
    the corresponding shell vars."""
    v3_path = (f"{tmp_path}/{expected_filename}"
               if version == "v3" else "")
    v3_1_path = (f"{tmp_path}/{expected_filename}"
                 if version == "v3.1" else "")
    v3_2_path = (f"{tmp_path}/{expected_filename}"
                 if version == "v3.2" else "")
    rc, stdout, stderr = _run_dispatch(
        version, tmp_path, "_slide_compose_prompt_path",
        slide_compose_v3_concat_path=v3_path,
        slide_compose_v3_1_concat_path=v3_1_path,
        slide_compose_v3_2_concat_path=v3_2_path)
    assert rc == 0, f"helper failed: {stderr}"
    assert stdout == f"{tmp_path}/{expected_filename}"


# ---------------------------------------------------------------------------
# Flag validation
# ---------------------------------------------------------------------------

def test_invalid_prompts_version_exits_2(tmp_path):
    """Per D-074: --prompts-version must be v1|v2|v3; anything else
    exits 2 with a clear error. The validation runs after BERIL_ROOT/
    project resolution so we need a project that exists; using an
    existing v0.5-vintage project keeps the test fast."""
    # Use an existing fixture project; we expect to exit at the
    # --prompts-version validation step, BEFORE any pipeline work.
    beril_root = (Path("/Users/aparkin/Documents/Claude/Projects/"
                       "research-coscientist-dev/spike/beril-extended"))
    project = "ibd_phage_targeting"
    result = subprocess.run(
        ["bash", str(ORCH_SH), project,
         "--beril-root", str(beril_root),
         "--prompts-version", "v9"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 2, (
        f"expected rc=2 on invalid version; got {result.returncode}")
    assert "--prompts-version must be" in result.stderr
    assert "v9" in result.stderr


def test_help_includes_prompts_version_flag():
    """Discoverability: --help output names --prompts-version flag +
    the three valid values."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    assert "--prompts-version" in help_text
    # All three valid values mentioned somewhere in the flag docs
    assert "v1" in help_text
    assert "v2" in help_text
    assert "v3" in help_text
    # D-074 default-v2 posture mentioned
    assert "v2" in help_text and "Default" in help_text


# ---------------------------------------------------------------------------
# v3 prompt-file existence (pre-flight)
# ---------------------------------------------------------------------------

def test_v3_prompt_files_present_in_pre_flight_check():
    """v0.5.1/D-075 + D-078: v3 prompts are now overlay files
    (`substory_design.v3_overlay.md` + `slide_compose.v3_overlay.md`),
    not the broken standalone v3.md files. The pre-flight check must
    require both overlays."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Find the pre-flight for loop
    pattern = r'^for f in (.+?); do$'
    matches = re.findall(pattern, text, re.MULTILINE)
    # Find the one containing slide_compose
    loop_line = next((m for m in matches if "slide_compose" in m), "")
    assert "substory_design.v3_overlay.md" in loop_line, (
        f"pre-flight prompt loop missing substory_design.v3_overlay.md; "
        f"got: {loop_line}")
    assert "slide_compose.v3_overlay.md" in loop_line, (
        f"pre-flight prompt loop missing slide_compose.v3_overlay.md; "
        f"got: {loop_line}")
    # The old standalone v3.md files must NOT be referenced — they
    # were deleted at v0.5.1 Tier A + A.2 (D-075 + D-078).
    # Use regex word-boundary so `substory_design.v3_overlay.md`
    # doesn't false-match `substory_design.v3.md`.
    assert not re.search(r'\bsubstory_design\.v3\.md\b', loop_line), (
        f"pre-flight still references retired substory_design.v3.md; "
        f"replace with substory_design.v3_overlay.md per D-078. "
        f"got: {loop_line}")
    assert not re.search(r'\bslide_compose\.v3\.md\b', loop_line), (
        f"pre-flight still references retired slide_compose.v3.md; "
        f"replace with slide_compose.v3_overlay.md per D-075. "
        f"got: {loop_line}")


# ---------------------------------------------------------------------------
# v0.5 Tier A.2 — SUBSTORY_QUESTION/CONCLUSION user-prompt wiring (D-071/D-072)
# ---------------------------------------------------------------------------
#
# The v3 slide_compose.v3.md prompt documents 3 user-prompt inputs that
# v2 doesn't have: SUBSTORY_QUESTION, SUBSTORY_CONCLUSION, ALLOWLIST_TERMS.
# Tier A.2 wired these through both slide-compose paths (v0_4 parallel +
# v0_3 sequential). Gate: only injected when --prompts-version v3.

def test_v0_4_user_prompt_injects_v3_fields_when_prompts_version_v3():
    """The v0_4 _compose_one_substory builder must include the three
    v3 user-prompt fields (SUBSTORY_QUESTION, SUBSTORY_CONCLUSION,
    ALLOWLIST_TERMS) inside a PROMPTS_VERSION=v3 gate."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Locate the v0_4 path's v3-gated injection block.
    # Look for the conditional block that adds SUBSTORY_QUESTION etc.
    assert 'SUBSTORY_QUESTION=$sub_question' in text, (
        "v3-gated injection of SUBSTORY_QUESTION missing")
    assert 'SUBSTORY_CONCLUSION=$sub_conclusion' in text, (
        "v3-gated injection of SUBSTORY_CONCLUSION missing")
    # ALLOWLIST_TERMS appears in BOTH v0_4 + v0_3 paths
    assert 'ALLOWLIST_TERMS=' in text, (
        "v3-gated injection of ALLOWLIST_TERMS missing")
    # Gate must be PROMPTS_VERSION=v3 (else injection happens on v1/v2 too)
    assert 'PROMPTS_VERSION" == "v3"' in text or \
           'PROMPTS_VERSION = v3' in text, (
        "v3 injection block missing PROMPTS_VERSION=v3 gate")


def test_v0_4_prepopulates_question_conclusion_brief_when_v3():
    """The v0_4 setup block (before per-substory compose) must
    pre-populate _M3_BRIEF_QUESTIONS + _M3_BRIEF_CONCLUSIONS via
    parse_deck_outline.py — and only when PROMPTS_VERSION=v3 (we
    don't pay parse-cost on v1/v2 paths)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert '_M3_BRIEF_QUESTIONS=' in text
    assert '_M3_BRIEF_CONCLUSIONS=' in text
    # And they're set inside a v3 gate (not unconditional)
    # Find the line numbers of the assignments
    lines = text.splitlines()
    questions_line = next(
        (i for i, line in enumerate(lines) if '_M3_BRIEF_QUESTIONS=' in line
         and '_m3_outline_field' in line), None)
    assert questions_line is not None, (
        "could not find _M3_BRIEF_QUESTIONS assignment with _m3_outline_field")
    # Look back ~10 lines for a PROMPTS_VERSION check
    preceding = "\n".join(lines[max(0, questions_line - 10):questions_line])
    assert 'PROMPTS_VERSION" == "v3"' in preceding, (
        "_M3_BRIEF_QUESTIONS assignment not gated by PROMPTS_VERSION=v3")


def test_v0_3_path_also_wires_v3_fields_when_prompts_version_v3():
    """The v0_3 sequential path (_slide_compose_v0_3) must ALSO
    wire SUBSTORY_QUESTION + SUBSTORY_CONCLUSION + ALLOWLIST_TERMS
    when PROMPTS_VERSION=v3, since v0_3 + v3 is a valid combination
    per D-074."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Locate the v0_3 function
    v0_3_start = text.find("_slide_compose_v0_3() {")
    assert v0_3_start > 0
    # Walk forward to find the function's end (next `^}` at column 0)
    # — heuristic: function bodies in this script are short enough that
    # the next `\n}\n` is the closer.
    v0_3_end = text.find("\n}\n", v0_3_start) + 2
    v0_3_body = text[v0_3_start:v0_3_end]
    # The body must contain v3-gated injection
    assert 'SUBSTORY_QUESTION=$sub_question' in v0_3_body, (
        "v0_3 path missing SUBSTORY_QUESTION v3-gated injection")
    assert 'SUBSTORY_CONCLUSION=$sub_conclusion' in v0_3_body, (
        "v0_3 path missing SUBSTORY_CONCLUSION v3-gated injection")
    assert 'PROMPTS_VERSION" == "v3"' in v0_3_body, (
        "v0_3 path missing PROMPTS_VERSION=v3 gate")


def test_parse_deck_outline_supports_v3_question_conclusion_fields():
    """parse_deck_outline.py --field {questions,conclusions} must be
    valid (the orchestrator's _m3_outline_field helper calls them).
    Quick sanity check via --help."""
    result = subprocess.run(
        [sys.executable,
         str(REPO_ROOT / "src/beril_presentation_maker/skill/tools/parse_deck_outline.py"),
         "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    help_text = result.stdout + result.stderr
    assert "questions" in help_text
    assert "conclusions" in help_text


def test_allowlist_loaded_from_project_dir_when_v3():
    """Per D-072: when PROMPTS_VERSION=v3, the orchestrator loads
    references/register_allowlist.md from PROJECT_DIR and injects as
    ALLOWLIST_TERMS (comma-separated). The load uses grep to strip
    comments + blanks."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # The allowlist path pattern must reference references/register_allowlist.md
    assert "references/register_allowlist.md" in text
    # Loaded via grep + tr to comma-separated string
    assert "register_allowlist.md" in text and "tr '\\n' ','" in text


# ---------------------------------------------------------------------------
# v0.5.1 Tier A — build_v3_concat_prompts() (D-075)
# ---------------------------------------------------------------------------
#
# build_v3_concat_prompts() runs once at orchestrator start (after
# set_draft_paths) and produces:
#   $AUDIT_DIR/_prompts/slide_compose.v3.concat.md
# = cat slide_compose.v2.md slide_compose.v3_overlay.md
#
# It populates SLIDE_COMPOSE_V3_CONCAT_PATH so the dispatcher echoes
# the concat path on --prompts-version v3.

def _extract_function(text: str, fname: str) -> str:
    """Pull a bash function body (including the `name() { ... }`)
    out of the orchestrator source. Heuristic — the orchestrator's
    function bodies are short and end at `^}` at column 0."""
    start = text.find(f"{fname}() {{")
    if start < 0:
        raise AssertionError(f"could not locate function {fname}")
    end = text.find("\n}\n", start) + 2
    return text[start:end]


def test_build_v3_concat_creates_audit_prompts_file(tmp_path):
    """build_v3_concat_prompts must write BOTH concat files under
    $AUDIT_DIR/_prompts/ with the v1/v2 body first + v3 overlay last
    in each case (D-075 for slide_compose; D-078 for substory_design)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    fn_src = _extract_function(text, "build_v3_concat_prompts")
    # Stage all four fake source files (slide_compose v2 + overlay;
    # substory_design v1 + overlay) so the function can read them.
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "slide_compose.v2.md").write_text(
        "==V2-SLIDE-MARKER==\nv2 slide_compose content\n", encoding="utf-8")
    (prompts_dir / "slide_compose.v3_overlay.md").write_text(
        "==V3-SLIDE-OVERLAY-MARKER==\nslide overlay content\n",
        encoding="utf-8")
    (prompts_dir / "substory_design.v1.md").write_text(
        "==V1-SUBSTORY-MARKER==\nv1 substory_design content\n",
        encoding="utf-8")
    (prompts_dir / "substory_design.v3_overlay.md").write_text(
        "==V3-SUBSTORY-OVERLAY-MARKER==\nsubstory overlay content\n",
        encoding="utf-8")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        PROMPTS_VERSION=v3
        PROMPTS_DIR={prompts_dir!s}
        AUDIT_DIR={audit_dir!s}
        SLIDE_COMPOSE_V3_CONCAT_PATH=""
        SUBSTORY_DESIGN_V3_CONCAT_PATH=""
        {fn_src}
        build_v3_concat_prompts
        echo "RET_SLIDE=$SLIDE_COMPOSE_V3_CONCAT_PATH"
        echo "RET_SUBSTORY=$SUBSTORY_DESIGN_V3_CONCAT_PATH"
        """)
    result = subprocess.run(["bash", "-c", wrapper],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

    # --- slide_compose concat ---
    slide_concat = audit_dir / "_prompts" / "slide_compose.v3.concat.md"
    assert slide_concat.is_file(), (
        f"build_v3_concat_prompts didn't write slide_compose concat at "
        f"{slide_concat}; stderr: {result.stderr}")
    slide_body = slide_concat.read_text(encoding="utf-8")
    v2_pos = slide_body.find("==V2-SLIDE-MARKER==")
    slide_overlay_pos = slide_body.find("==V3-SLIDE-OVERLAY-MARKER==")
    assert v2_pos >= 0 and slide_overlay_pos >= 0
    assert v2_pos < slide_overlay_pos, (
        f"slide_compose concat order wrong: v2 at {v2_pos}, overlay at "
        f"{slide_overlay_pos}; overlay must come LAST")

    # --- substory_design concat ---
    substory_concat = audit_dir / "_prompts" / "substory_design.v3.concat.md"
    assert substory_concat.is_file(), (
        f"build_v3_concat_prompts didn't write substory_design concat at "
        f"{substory_concat}; stderr: {result.stderr}")
    substory_body = substory_concat.read_text(encoding="utf-8")
    v1_pos = substory_body.find("==V1-SUBSTORY-MARKER==")
    substory_overlay_pos = substory_body.find(
        "==V3-SUBSTORY-OVERLAY-MARKER==")
    assert v1_pos >= 0 and substory_overlay_pos >= 0
    assert v1_pos < substory_overlay_pos, (
        f"substory_design concat order wrong: v1 at {v1_pos}, overlay "
        f"at {substory_overlay_pos}; overlay must come LAST")

    # Shell vars must be populated for the dispatcher.
    assert f"RET_SLIDE={slide_concat}" in result.stdout
    assert f"RET_SUBSTORY={substory_concat}" in result.stdout


def test_build_v3_concat_no_op_for_v1_v2(tmp_path):
    """build_v3_concat_prompts must early-return when PROMPTS_VERSION
    is not v3 (no concat, no shell-var population)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    fn_src = _extract_function(text, "build_v3_concat_prompts")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    for version in ("v1", "v2"):
        wrapper = textwrap.dedent(f"""\
            set -euo pipefail
            PROMPTS_VERSION={version}
            PROMPTS_DIR={prompts_dir!s}
            AUDIT_DIR={audit_dir!s}
            SLIDE_COMPOSE_V3_CONCAT_PATH=""
            SUBSTORY_DESIGN_V3_CONCAT_PATH=""
            {fn_src}
            build_v3_concat_prompts
            echo "RET_SLIDE=$SLIDE_COMPOSE_V3_CONCAT_PATH"
            """)
        result = subprocess.run(["bash", "-c", wrapper],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        # No concat file written.
        assert not (audit_dir / "_prompts" /
                    "slide_compose.v3.concat.md").exists()
        # Shell var stays empty.
        assert "RET_SLIDE=" in result.stdout
        # The line should be exactly "RET_SLIDE=" (nothing after =).
        for line in result.stdout.splitlines():
            if line.startswith("RET_SLIDE="):
                assert line == "RET_SLIDE=", (
                    f"v1/v2 path leaked into concat path: {line!r}")


def test_v3_overlay_file_present_on_disk():
    """Belt + suspenders: BOTH v3 overlay files actually exist at the
    expected path in the repo (so build_v3_concat_prompts won't fail
    with ENOENT at orchestrator start)."""
    prompts = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
               / "prompts")
    slide_overlay = prompts / "slide_compose.v3_overlay.md"
    substory_overlay = prompts / "substory_design.v3_overlay.md"
    assert slide_overlay.is_file(), (
        f"slide_compose v3 overlay missing at {slide_overlay}")
    assert substory_overlay.is_file(), (
        f"substory_design v3 overlay missing at {substory_overlay}")
    # Each body should self-identify as a v3 overlay and reference
    # its v1/v2 dependency.
    slide_body = slide_overlay.read_text(encoding="utf-8")
    assert "v3 overlay" in slide_body.lower()
    assert "v2" in slide_body, (
        "slide_compose overlay doesn't reference v2 — concat assumption "
        "suspect")
    substory_body = substory_overlay.read_text(encoding="utf-8")
    assert "v3 overlay" in substory_body.lower()
    assert "v1" in substory_body, (
        "substory_design overlay doesn't reference v1 — concat "
        "assumption suspect")


def test_old_standalone_v3_files_retired():
    """v0.5.1 Tier A + A.2 retire `slide_compose.v3.md` AND
    `substory_design.v3.md` (the broken standalone files). Their
    content lives in the overlay+concat pattern now. Belt-and-
    suspenders against a future accidental re-creation."""
    prompts = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
               / "prompts")
    old_slide = prompts / "slide_compose.v3.md"
    old_substory = prompts / "substory_design.v3.md"
    assert not old_slide.exists(), (
        f"standalone slide_compose.v3.md came back at {old_slide}; "
        f"v0.5.1/D-075 replaced it with slide_compose.v3_overlay.md. "
        f"If you intentionally re-introduced it, update this test + "
        f"the dispatcher to match.")
    assert not old_substory.exists(), (
        f"standalone substory_design.v3.md came back at "
        f"{old_substory}; v0.5.1/D-078 replaced it with "
        f"substory_design.v3_overlay.md. If you intentionally "
        f"re-introduced it, update this test + the dispatcher to "
        f"match.")


# ---------------------------------------------------------------------------
# v0.5.1 Tier A.1 — overlay anti-pattern field names (D-077)
# ---------------------------------------------------------------------------
#
# The pre-fix overlay (and the dead standalone v3.md before it)
# called claim_evidence's principal-text field `punchline` — wrong.
# v2's per-layout schema requires `title` for claim_evidence
# (annotated "the punchline; declarative"). Same bug appeared for
# the C-slide self-check + the C-slide anti-pattern bullet + the
# inviolable rules.
#
# Pin the corrected references so a future re-edit can't regress.

OVERLAY_PATH = (REPO_ROOT / "src" / "beril_presentation_maker"
                / "skill" / "prompts" / "slide_compose.v3_overlay.md")


def test_c_slide_references_claim_evidence_title_not_punchline():
    """Per D-077: claim_evidence's required-field is `title` (not
    `punchline`). The overlay's C-slide guidance + self-check +
    anti-pattern + inviolable-rules must reference `title` when
    talking about claim_evidence — anywhere the overlay says
    'claim_evidence schema ... punchline' is the bug we fixed."""
    body = OVERLAY_PATH.read_text(encoding="utf-8")
    # Find the C-slide section (between "**C-slide" and "## ").
    c_slide_start = body.find("**C-slide")
    assert c_slide_start > 0
    c_slide_end = body.find("\n## ", c_slide_start)
    c_slide_block = body[c_slide_start:c_slide_end]
    # Must reference `title` (the correct v2 field name)
    assert "`title`" in c_slide_block, (
        "C-slide section should reference `title` (v2's "
        "claim_evidence required-field); got block:\n"
        f"{c_slide_block[:500]}")
    # The dead-bug phrasing — "claim_evidence schema defines the
    # `punchline` field" — must NOT appear.
    assert "claim_evidence` defines the `punchline" not in c_slide_block
    assert "claim_evidence schema ... punchline" not in c_slide_block

    # And anywhere the anti-pattern / inviolable-rule names the
    # field on claim_evidence, it should say `title`, not `punchline`.
    # Find the v3-anti-patterns section.
    ap_start = body.find("## v3 anti-patterns")
    ap_end = body.find("\n## ", ap_start)
    ap_block = body[ap_start:ap_end]
    # C-slide-without-conclusion bullet exists + names `title`.
    assert "C-slide without conclusion" in ap_block
    assert "claim_evidence whose\n  `title`" in ap_block or \
           "claim_evidence whose `title`" in ap_block, (
        "C-slide-without-conclusion anti-pattern bullet should "
        "reference `title` (the v2 claim_evidence field), not "
        "`punchline`; got block:\n" + ap_block[:600])


def test_q_slide_references_section_divider_punchline():
    """Per v2's section_divider schema (slide_compose.v2.md L569):
    the required field is `punchline`. The Q-slide anti-pattern
    bullet must name `punchline` (not `title`) — this is the OTHER
    half of D-077. (The pre-fix overlay actually got this right;
    pin to prevent regression.)"""
    body = OVERLAY_PATH.read_text(encoding="utf-8")
    ap_start = body.find("## v3 anti-patterns")
    ap_end = body.find("\n## ", ap_start)
    ap_block = body[ap_start:ap_end]
    assert "Q-slide without question" in ap_block
    # The pin: section_divider's field is `punchline`.
    assert "section_divider whose\n  `punchline`" in ap_block or \
           "section_divider whose `punchline`" in ap_block, (
        "Q-slide-without-question anti-pattern bullet should "
        "reference `punchline` (the v2 section_divider field), "
        "not `title`; got block:\n" + ap_block[:600])


# ---------------------------------------------------------------------------
# v0.5.1 Tier B — D-076 smoke-pass gate
# ---------------------------------------------------------------------------
#
# When --prompts-version v3 is passed, the orchestrator must
# refuse to run unless `tools/smoke_v3_prompt.py --check-recent`
# returns rc=0. Bypass via --force-v3-smoke-stale.

def test_orchestrator_rejects_v3_when_no_smoke_pass_record(tmp_path):
    """A fresh checkout (no audit/v3_smoke_pass.json) + invocation
    with --prompts-version v3 must exit rc=2 with a clear message
    telling the operator to run the smoke or use --force."""
    # The orchestrator's gate-check uses the smoke tool's own
    # SMOKE_DIR/PASS_RECORD, which is a fixed path under the skill
    # repo root. To exercise the rejection branch we use HOME
    # override on the smoke tool's record path won't work via env
    # — easier: assert that the gate-check code block exists +
    # correctly fires when the real PASS_RECORD is absent.
    # The "exists" pin is in test_orchestrator_has_v3_smoke_gate
    # below; this test runs the orchestrator with v3 + EXPECTS rc=2
    # IFF the pass record is absent at the moment of test.
    pass_record = (REPO_ROOT / "audit" / "v3_smoke_pass.json")
    if pass_record.is_file():
        pytest.skip(
            "v3 smoke-pass record exists; gate-rejection path can't "
            "be exercised. Move/rename the record + re-run to test "
            "the rejection branch.")
    beril_root = (Path("/Users/aparkin/Documents/Claude/Projects/"
                       "research-coscientist-dev/spike/beril-extended"))
    project = "ibd_phage_targeting"
    if not (beril_root / "projects" / project).is_dir():
        pytest.skip(f"fixture project missing at {beril_root}/projects/"
                    f"{project}")
    result = subprocess.run(
        ["bash", str(ORCH_SH), project,
         "--beril-root", str(beril_root),
         "--prompts-version", "v3"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2, (
        f"expected rc=2 on v3 without smoke-pass record; got "
        f"{result.returncode}; stderr:\n{result.stderr[-2000:]}")
    assert "smoke-pass record" in result.stderr or \
           "smoke_v3_prompt.py" in result.stderr, (
        "stderr should explain the smoke-gate failure; got:\n"
        f"{result.stderr[-2000:]}")


def test_orchestrator_has_v3_smoke_gate():
    """The orchestrator source must include the D-076 gate-check
    code path. Pin the literal strings so a future refactor
    can't accidentally drop the gate."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Gate-check block must reference the smoke tool + check-recent
    assert "smoke_v3_prompt.py" in text
    assert "--check-recent" in text
    # Gate guards on PROMPTS_VERSION=v3 + FORCE_V3_SMOKE_STALE
    assert 'PROMPTS_VERSION" == "v3"' in text
    assert 'FORCE_V3_SMOKE_STALE' in text
    # Bypass flag exists in arg parser
    assert '--force-v3-smoke-stale' in text


def test_orchestrator_help_documents_force_v3_smoke_stale():
    """The --help docstring lists --force-v3-smoke-stale so
    operators discover it when the gate rejects them."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    assert "--force-v3-smoke-stale" in help_text


def test_inviolable_rules_name_both_field_names_explicitly():
    """The inviolable-rules section must enumerate the
    layout-specific field names for both Q-slide layouts
    (section_divider→punchline, big_idea→title) and C-slide layouts
    (claim_evidence→title, big_idea→title). The pre-fix overlay
    used only the vague 'principal-text field' language; D-077
    strengthens it to name the fields explicitly."""
    body = OVERLAY_PATH.read_text(encoding="utf-8")
    # Find the inviolable-rules section header.
    inv_start = body.find("## v3 inviolable rules")
    inv_end = len(body)  # rules is the last section
    inv_block = body[inv_start:inv_end]
    # The Q-slide rule must name `section_divider` → `punchline`
    # AND `big_idea` → `title`.
    assert "section_divider" in inv_block and "punchline" in inv_block, (
        "Q-slide inviolable rule should name section_divider + "
        "punchline; got:\n" + inv_block[:800])
    # The C-slide rule must name `claim_evidence` → `title`.
    assert "claim_evidence" in inv_block and "title" in inv_block, (
        "C-slide inviolable rule should name claim_evidence + "
        "title; got:\n" + inv_block[:800])
    # And the rule must explicitly warn against generic-name
    # substitution (the lesson from the morning abort).
    assert "Do NOT" in inv_block or "do NOT" in inv_block, (
        "Inviolable rule should explicitly warn against generic-"
        "name substitution per D-077 lesson; got:\n" +
        inv_block[:800])


# ---------------------------------------------------------------------------
# v0.6 Tier A — v3.1 overlay + stacked concat (D-080)
# ---------------------------------------------------------------------------
#
# v3.1 stacks the figure-utilization overlay onto the v3 chain:
#   cat slide_compose.v2.md + .v3_overlay.md + .v3.1_overlay.md
# Distinct concat path so a v3 smoke-pass record doesn't accidentally
# satisfy a v3.1 gate-check (the prompt-body sha differs).
#
# substory_design v3.1 reuses the v3 substory_design concat (D-080
# doesn't change substory_design — only slide_compose carries the
# figure-utilization overlay).

V3_1_OVERLAY_PATH = (REPO_ROOT / "src" / "beril_presentation_maker"
                     / "skill" / "prompts" / "slide_compose.v3.1_overlay.md")


def test_v3_1_overlay_file_present_on_disk():
    """Belt + suspenders: the v3.1 overlay file ships with the repo
    (so build_v3_concat_prompts can stack it on v3 at orchestrator
    start)."""
    assert V3_1_OVERLAY_PATH.is_file(), (
        f"v3.1 overlay missing at {V3_1_OVERLAY_PATH}")
    body = V3_1_OVERLAY_PATH.read_text(encoding="utf-8")
    # Self-identifies as v3.1
    assert "v3.1" in body.lower()
    # References stacking on v3 (the concat-order contract)
    assert "v3_overlay" in body, (
        "overlay should reference v3_overlay (the v3 chain it stacks on)")
    # References v2 (the body it ultimately concats with)
    assert "v2" in body


def test_prompts_version_validation_accepts_v3_1():
    """`--prompts-version v3.1` must pass the validation case;
    `v3.2`/`v4`/etc. still reject."""
    beril_root = (Path("/Users/aparkin/Documents/Claude/Projects/"
                       "research-coscientist-dev/spike/beril-extended"))
    if not (beril_root / "projects" / "ibd_phage_targeting").is_dir():
        pytest.skip("fixture project missing")
    # v3.1 valid → must NOT hit the validation rc=2 branch. We can't
    # easily run a real v3.1 invocation (smoke gate will reject without
    # a v3.1 pass record), so test the validation block by passing an
    # INVALID version and confirming the error message lists v3.1.
    result = subprocess.run(
        ["bash", str(ORCH_SH), "ibd_phage_targeting",
         "--beril-root", str(beril_root),
         "--prompts-version", "v9"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 2
    assert "v1|v2|v3|v3.1" in result.stderr, (
        f"validation error message should list v3.1 as accepted; "
        f"got:\n{result.stderr[-500:]}")


def test_build_v3_concat_creates_v3_1_concat_when_v3_1(tmp_path):
    """When PROMPTS_VERSION=v3.1, build_v3_concat_prompts must stack
    the v3.1 overlay onto the v3 chain and write a SEPARATE concat
    file (slide_compose.v3.1.concat.md). The v3 concat is also
    written (it's the substrate); both shell vars get populated."""
    text = ORCH_SH.read_text(encoding="utf-8")
    fn_src = _extract_function(text, "build_v3_concat_prompts")
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    # Stage all source files build_v3_concat_prompts reads.
    (prompts_dir / "slide_compose.v2.md").write_text(
        "==V2-SLIDE-MARKER==\nv2 content\n", encoding="utf-8")
    (prompts_dir / "slide_compose.v3_overlay.md").write_text(
        "==V3-SLIDE-OVERLAY-MARKER==\nv3 overlay\n", encoding="utf-8")
    (prompts_dir / "slide_compose.v3.1_overlay.md").write_text(
        "==V3-1-SLIDE-OVERLAY-MARKER==\nv3.1 figure overlay\n",
        encoding="utf-8")
    (prompts_dir / "substory_design.v1.md").write_text(
        "==V1-SUBSTORY-MARKER==\nv1 substory\n", encoding="utf-8")
    (prompts_dir / "substory_design.v3_overlay.md").write_text(
        "==V3-SUBSTORY-OVERLAY-MARKER==\nv3 substory overlay\n",
        encoding="utf-8")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        PROMPTS_VERSION=v3.1
        PROMPTS_DIR={prompts_dir!s}
        AUDIT_DIR={audit_dir!s}
        SLIDE_COMPOSE_V3_CONCAT_PATH=""
        SUBSTORY_DESIGN_V3_CONCAT_PATH=""
        SLIDE_COMPOSE_V3_1_CONCAT_PATH=""
        {fn_src}
        build_v3_concat_prompts
        echo "RET_V3=$SLIDE_COMPOSE_V3_CONCAT_PATH"
        echo "RET_V3_1=$SLIDE_COMPOSE_V3_1_CONCAT_PATH"
        echo "RET_SUBSTORY=$SUBSTORY_DESIGN_V3_CONCAT_PATH"
        """)
    result = subprocess.run(["bash", "-c", wrapper],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

    # v3 concat exists (substrate)
    v3_concat = audit_dir / "_prompts" / "slide_compose.v3.concat.md"
    assert v3_concat.is_file()
    # v3.1 concat exists (stacked)
    v3_1_concat = audit_dir / "_prompts" / "slide_compose.v3.1.concat.md"
    assert v3_1_concat.is_file()
    # v3.1 concat contains markers in order: v2 + v3-overlay + v3.1-overlay
    body = v3_1_concat.read_text(encoding="utf-8")
    v2_pos = body.find("==V2-SLIDE-MARKER==")
    v3_pos = body.find("==V3-SLIDE-OVERLAY-MARKER==")
    v3_1_pos = body.find("==V3-1-SLIDE-OVERLAY-MARKER==")
    assert v2_pos >= 0 and v3_pos >= 0 and v3_1_pos >= 0
    assert v2_pos < v3_pos < v3_1_pos, (
        f"concat order wrong: v2 at {v2_pos}, v3-overlay at {v3_pos}, "
        f"v3.1-overlay at {v3_1_pos}; expected ascending")
    # Shell vars populated
    assert f"RET_V3_1={v3_1_concat}" in result.stdout
    assert f"RET_V3={v3_concat}" in result.stdout


def test_build_v3_concat_v3_path_does_NOT_create_v3_1_concat(tmp_path):
    """Running with PROMPTS_VERSION=v3 must produce ONLY the v3 concat,
    not the v3.1 one. The v3.1 concat path stays empty."""
    text = ORCH_SH.read_text(encoding="utf-8")
    fn_src = _extract_function(text, "build_v3_concat_prompts")
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "slide_compose.v2.md").write_text("v2\n",
                                                     encoding="utf-8")
    (prompts_dir / "slide_compose.v3_overlay.md").write_text(
        "v3 overlay\n", encoding="utf-8")
    (prompts_dir / "slide_compose.v3.1_overlay.md").write_text(
        "v3.1 overlay\n", encoding="utf-8")
    (prompts_dir / "substory_design.v1.md").write_text("v1\n",
                                                       encoding="utf-8")
    (prompts_dir / "substory_design.v3_overlay.md").write_text(
        "v3 sub overlay\n", encoding="utf-8")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        PROMPTS_VERSION=v3
        PROMPTS_DIR={prompts_dir!s}
        AUDIT_DIR={audit_dir!s}
        SLIDE_COMPOSE_V3_CONCAT_PATH=""
        SUBSTORY_DESIGN_V3_CONCAT_PATH=""
        SLIDE_COMPOSE_V3_1_CONCAT_PATH=""
        {fn_src}
        build_v3_concat_prompts
        echo "RET_V3_1=$SLIDE_COMPOSE_V3_1_CONCAT_PATH"
        """)
    result = subprocess.run(["bash", "-c", wrapper],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    # v3.1 concat must NOT exist (only built when PROMPTS_VERSION=v3.1)
    v3_1_concat = audit_dir / "_prompts" / "slide_compose.v3.1.concat.md"
    assert not v3_1_concat.exists()
    # Shell var stays empty
    for line in result.stdout.splitlines():
        if line.startswith("RET_V3_1="):
            assert line == "RET_V3_1=", (
                f"v3 path leaked v3.1 concat var: {line!r}")


def test_v3_gates_also_fire_for_v3_1():
    """The 6 orchestrator gates that fire SUBSTORY_QUESTION/CONCLUSION/
    ALLOWLIST_TERMS injection on `PROMPTS_VERSION == v3` must ALSO
    fire on v3.1 + v3.2 (each successive v3.x stacks on v3; the v3
    user-prompt contract still applies). v0.6/D-080 changed those
    gates to OR-expressions including v3.1; v0.7/D-085 extends to
    include v3.2."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Count v3-OR-v3.1-OR-v3.2 gates; should be ≥ 6 (matches the
    # v0.5 + v0.5.1 sites we deliberately extended).
    count = text.count(
        '"$PROMPTS_VERSION" == "v3" || "$PROMPTS_VERSION" == "v3.1" '
        '|| "$PROMPTS_VERSION" == "v3.2"')
    assert count >= 6, (
        f"expected ≥6 OR-gates for v3+v3.1+v3.2; got {count}. Either "
        f"a gate was missed (regression risk) or the gates were "
        f"restructured (update this test).")
    # Sanity: no v3-only gate remains (regression risk that v3.1/v3.2
    # invocations don't get the v3 contract injection).
    v3_only = text.count('"$PROMPTS_VERSION" == "v3" ]]')
    assert v3_only == 0, (
        f"found {v3_only} v3-only PROMPTS_VERSION gate(s); v0.6/D-080 "
        f"+ v0.7/D-085 require they OR with v3.1 + v3.2.")
    # Sanity: no v3+v3.1-only gate (without v3.2) remains either.
    v3_and_v3_1_only = text.count(
        '"$PROMPTS_VERSION" == "v3" || "$PROMPTS_VERSION" == "v3.1" ]]')
    assert v3_and_v3_1_only == 0, (
        f"found {v3_and_v3_1_only} v3+v3.1-only PROMPTS_VERSION "
        f"gate(s); v0.7/D-085 requires they extend to also OR with v3.2.")


def test_v3_1_pre_flight_requires_v3_1_overlay():
    """The pre-flight prompt-existence loop must include
    `slide_compose.v3.1_overlay.md` so missing-overlay fails early
    instead of at orchestrator start with a cryptic ENOENT."""
    text = ORCH_SH.read_text(encoding="utf-8")
    pattern = r'^for f in (.+?); do$'
    matches = re.findall(pattern, text, re.MULTILINE)
    loop_line = next((m for m in matches if "slide_compose" in m), "")
    assert "slide_compose.v3.1_overlay.md" in loop_line, (
        f"pre-flight loop missing slide_compose.v3.1_overlay.md; "
        f"got: {loop_line}")


# ---------------------------------------------------------------------------
# v0.7 Tier A — v3.2 overlay + stacked concat (D-085)
# ---------------------------------------------------------------------------
#
# v3.2 stacks the figure-relevance refinement + deck_close + arc-
# transition USAGE overlay onto the v3.1 chain:
#   cat slide_compose.v2.md + .v3_overlay.md + .v3.1_overlay.md
#       + .v3.2_overlay.md
# Distinct concat path so a v3.1 smoke-pass record doesn't accidentally
# satisfy a v3.2 gate-check (the prompt-body sha differs).
#
# substory_design v3.2 Tier A reuses the v3 substory_design concat;
# Tier B / D-087 will add a substory_design v3.2 overlay (the
# `transition_from_prior` field emitter). The slide_compose overlay
# can already reference the field — it just won't be populated until
# Tier B ships.

V3_2_OVERLAY_PATH = (REPO_ROOT / "src" / "beril_presentation_maker"
                     / "skill" / "prompts" / "slide_compose.v3.2_overlay.md")


def test_v3_2_overlay_file_present_on_disk():
    """Belt + suspenders: the v3.2 overlay file ships with the repo
    (so build_v3_concat_prompts can stack it on v3.1 at orchestrator
    start)."""
    assert V3_2_OVERLAY_PATH.is_file(), (
        f"v3.2 overlay missing at {V3_2_OVERLAY_PATH}")
    body = V3_2_OVERLAY_PATH.read_text(encoding="utf-8")
    # Self-identifies as v3.2
    assert "v3.2" in body.lower()
    # References stacking on v3.1 (the concat-order contract)
    assert "v3.1_overlay" in body, (
        "v3.2 overlay should reference v3.1_overlay (the chain it "
        "stacks on)")
    # References v2 (the body it ultimately concats with)
    assert "v2" in body
    # The three v0.7 contracts are mentioned by name
    assert "D-085" in body, "v3.2 overlay should cite D-085 (figure-relevance)"
    assert "D-086" in body, "v3.2 overlay should cite D-086 (deck_close)"
    assert "D-087" in body, "v3.2 overlay should cite D-087 (transitions)"
    # Adam-direction pin from D-085: no figure budgeting
    body_lower = body.lower()
    assert "budget" in body_lower, (
        "v3.2 overlay should explain the no-figure-budget framing "
        "from Adam DQ1 (the change from v3.1's per-substory ≥1 rule)")


def test_prompts_version_validation_accepts_v3_2():
    """`--prompts-version v3.2` must pass the validation case;
    `v3.3`/`v4`/etc. still reject."""
    beril_root = (Path("/Users/aparkin/Documents/Claude/Projects/"
                       "research-coscientist-dev/spike/beril-extended"))
    if not (beril_root / "projects" / "ibd_phage_targeting").is_dir():
        pytest.skip("fixture project missing")
    # v3.2 valid → must NOT hit the validation rc=2 branch. We can't
    # easily run a real v3.2 invocation (smoke gate will reject
    # without a v3.2 pass record), so test the validation block by
    # passing an INVALID version and confirming the error message
    # lists v3.2.
    result = subprocess.run(
        ["bash", str(ORCH_SH), "ibd_phage_targeting",
         "--beril-root", str(beril_root),
         "--prompts-version", "v9"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 2
    assert "v1|v2|v3|v3.1|v3.2" in result.stderr, (
        f"validation error message should list v3.2 as accepted; "
        f"got:\n{result.stderr[-500:]}")


def test_build_v3_concat_creates_v3_2_concat_when_v3_2(tmp_path):
    """When PROMPTS_VERSION=v3.2, build_v3_concat_prompts must stack
    the v3.2 overlay onto the v3.1 chain and write a SEPARATE concat
    file (slide_compose.v3.2.concat.md). The v3 + v3.1 concats are
    also written (they're the substrate); all three shell vars get
    populated."""
    text = ORCH_SH.read_text(encoding="utf-8")
    fn_src = _extract_function(text, "build_v3_concat_prompts")
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    # Stage all source files build_v3_concat_prompts reads.
    (prompts_dir / "slide_compose.v2.md").write_text(
        "==V2-SLIDE-MARKER==\nv2 content\n", encoding="utf-8")
    (prompts_dir / "slide_compose.v3_overlay.md").write_text(
        "==V3-SLIDE-OVERLAY-MARKER==\nv3 overlay\n", encoding="utf-8")
    (prompts_dir / "slide_compose.v3.1_overlay.md").write_text(
        "==V3-1-SLIDE-OVERLAY-MARKER==\nv3.1 figure overlay\n",
        encoding="utf-8")
    (prompts_dir / "slide_compose.v3.2_overlay.md").write_text(
        "==V3-2-SLIDE-OVERLAY-MARKER==\nv3.2 figure-relevance overlay\n",
        encoding="utf-8")
    (prompts_dir / "substory_design.v1.md").write_text(
        "==V1-SUBSTORY-MARKER==\nv1 substory\n", encoding="utf-8")
    (prompts_dir / "substory_design.v3_overlay.md").write_text(
        "==V3-SUBSTORY-OVERLAY-MARKER==\nv3 substory overlay\n",
        encoding="utf-8")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        PROMPTS_VERSION=v3.2
        PROMPTS_DIR={prompts_dir!s}
        AUDIT_DIR={audit_dir!s}
        SLIDE_COMPOSE_V3_CONCAT_PATH=""
        SUBSTORY_DESIGN_V3_CONCAT_PATH=""
        SLIDE_COMPOSE_V3_1_CONCAT_PATH=""
        SLIDE_COMPOSE_V3_2_CONCAT_PATH=""
        {fn_src}
        build_v3_concat_prompts
        echo "RET_V3=$SLIDE_COMPOSE_V3_CONCAT_PATH"
        echo "RET_V3_1=$SLIDE_COMPOSE_V3_1_CONCAT_PATH"
        echo "RET_V3_2=$SLIDE_COMPOSE_V3_2_CONCAT_PATH"
        echo "RET_SUBSTORY=$SUBSTORY_DESIGN_V3_CONCAT_PATH"
        """)
    result = subprocess.run(["bash", "-c", wrapper],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

    # v3 concat exists (substrate)
    v3_concat = audit_dir / "_prompts" / "slide_compose.v3.concat.md"
    assert v3_concat.is_file()
    # v3.1 concat exists (substrate)
    v3_1_concat = audit_dir / "_prompts" / "slide_compose.v3.1.concat.md"
    assert v3_1_concat.is_file()
    # v3.2 concat exists (stacked on top)
    v3_2_concat = audit_dir / "_prompts" / "slide_compose.v3.2.concat.md"
    assert v3_2_concat.is_file()
    # v3.2 concat contains markers in order:
    # v2 + v3-overlay + v3.1-overlay + v3.2-overlay
    body = v3_2_concat.read_text(encoding="utf-8")
    v2_pos = body.find("==V2-SLIDE-MARKER==")
    v3_pos = body.find("==V3-SLIDE-OVERLAY-MARKER==")
    v3_1_pos = body.find("==V3-1-SLIDE-OVERLAY-MARKER==")
    v3_2_pos = body.find("==V3-2-SLIDE-OVERLAY-MARKER==")
    assert all(p >= 0 for p in (v2_pos, v3_pos, v3_1_pos, v3_2_pos))
    assert v2_pos < v3_pos < v3_1_pos < v3_2_pos, (
        f"concat order wrong: v2={v2_pos}, v3-overlay={v3_pos}, "
        f"v3.1-overlay={v3_1_pos}, v3.2-overlay={v3_2_pos}; expected "
        f"strictly ascending")
    # All three slide_compose shell vars populated
    assert f"RET_V3={v3_concat}" in result.stdout
    assert f"RET_V3_1={v3_1_concat}" in result.stdout
    assert f"RET_V3_2={v3_2_concat}" in result.stdout


def test_build_v3_concat_v3_1_path_does_NOT_create_v3_2_concat(tmp_path):
    """Running with PROMPTS_VERSION=v3.1 must produce ONLY the v3 +
    v3.1 concats, NOT the v3.2 one. The v3.2 concat path stays empty."""
    text = ORCH_SH.read_text(encoding="utf-8")
    fn_src = _extract_function(text, "build_v3_concat_prompts")
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "slide_compose.v2.md").write_text("v2\n",
                                                     encoding="utf-8")
    (prompts_dir / "slide_compose.v3_overlay.md").write_text(
        "v3 overlay\n", encoding="utf-8")
    (prompts_dir / "slide_compose.v3.1_overlay.md").write_text(
        "v3.1 overlay\n", encoding="utf-8")
    (prompts_dir / "slide_compose.v3.2_overlay.md").write_text(
        "v3.2 overlay\n", encoding="utf-8")
    (prompts_dir / "substory_design.v1.md").write_text("v1\n",
                                                       encoding="utf-8")
    (prompts_dir / "substory_design.v3_overlay.md").write_text(
        "v3 sub overlay\n", encoding="utf-8")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        PROMPTS_VERSION=v3.1
        PROMPTS_DIR={prompts_dir!s}
        AUDIT_DIR={audit_dir!s}
        SLIDE_COMPOSE_V3_CONCAT_PATH=""
        SUBSTORY_DESIGN_V3_CONCAT_PATH=""
        SLIDE_COMPOSE_V3_1_CONCAT_PATH=""
        SLIDE_COMPOSE_V3_2_CONCAT_PATH=""
        {fn_src}
        build_v3_concat_prompts
        echo "RET_V3_2=$SLIDE_COMPOSE_V3_2_CONCAT_PATH"
        """)
    result = subprocess.run(["bash", "-c", wrapper],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    # v3.2 concat must NOT exist (only built when PROMPTS_VERSION=v3.2)
    v3_2_concat = audit_dir / "_prompts" / "slide_compose.v3.2.concat.md"
    assert not v3_2_concat.exists()
    # Shell var stays empty
    for line in result.stdout.splitlines():
        if line.startswith("RET_V3_2="):
            assert line == "RET_V3_2=", (
                f"v3.1 path leaked v3.2 concat var: {line!r}")


def test_v3_2_pre_flight_requires_v3_2_overlay():
    """The pre-flight prompt-existence loop must include
    `slide_compose.v3.2_overlay.md` so missing-overlay fails early
    instead of at orchestrator start with a cryptic ENOENT."""
    text = ORCH_SH.read_text(encoding="utf-8")
    pattern = r'^for f in (.+?); do$'
    matches = re.findall(pattern, text, re.MULTILINE)
    loop_line = next((m for m in matches if "slide_compose" in m), "")
    assert "slide_compose.v3.2_overlay.md" in loop_line, (
        f"pre-flight loop missing slide_compose.v3.2_overlay.md; "
        f"got: {loop_line}")


def test_v3_2_smoke_gate_fires_for_v3_2():
    """The D-076 smoke-pass gate must fire on PROMPTS_VERSION=v3.2
    (not just v3 + v3.1). Pin by checking the gate's case statement
    accepts v3.2."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Look for the _v3_family case block that sets _v3_family=1.
    # It must include v3.2 in the match arm.
    gate_block_start = text.find("case \"$PROMPTS_VERSION\" in\n"
                                  "  v3|v3.1|v3.2)")
    assert gate_block_start >= 0, (
        "smoke-pass gate's case block missing v3|v3.1|v3.2 match arm; "
        "v0.7/D-085 requires v3.2 trigger the D-076 gate")


def test_help_documents_v3_2():
    """--help output must document --prompts-version v3.2 and its
    place in the v3-family stack."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    assert "v3.2" in help_text, (
        "--help should mention v3.2 in --prompts-version flag docs")
    # v3.2's authoring contracts (D-085 / D-086 / D-087) should be
    # discoverable from --help so an operator knows what v3.2 adds.
    # We don't pin all three IDs here (low value), but the help text
    # should at least describe v3.2 in the same documentation block
    # as v3 + v3.1.
    assert "v3.2" in help_text and "v3.1" in help_text and "v3" in help_text
